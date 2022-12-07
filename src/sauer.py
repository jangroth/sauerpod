import email
import json
import logging
import os
import tempfile
import textwrap
import time
from collections import namedtuple
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from urllib import request

import boto3
import requests
from boto3.dynamodb.conditions import Key
from pytube import YouTube
from jinja2 import Environment, select_autoescape, PackageLoader


logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("SauerPod")
logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))


SSM_PATH_TELEGRAM_API_TOKEN = "/sauerpod/telegram/api-token"
SSM_PATH_TELEGRAM_CHAT_ID = "/sauerpod/telegram/chat-id"

VideoInformation = namedtuple(
    "VideoInformation",
    [
        "video_id",
        "title",
        "author",
        "description",
        "thumbnail_url",
        "duration_in_seconds",
        "keywords",
        "source_url",
    ],
)
UploadInformation = namedtuple(
    "UploadInformation",
    [
        "path_to_episode",
        "path_to_thumbnail",
        "timestamp_utc",
        "timestamp_rfc822",
        "episode_size",
    ],
)


def notify_cloudwatch(function):
    def wrapper(*args, **kwargs):
        incoming_event = args[0]  # ...event
        function_name = args[1].function_name
        logger.info(f"'{function_name}' - entry.\nIncoming event: '{incoming_event}'")
        result = function(*args, **kwargs)
        logger.info(f"'{function_name}' - exit.\n\nResult: '{result}'")
        return result

    return wrapper


class UnknownChatIdException(Exception):
    pass


class Status(Enum):
    DOWNLOADER = auto()
    COMMANDER = auto()
    UNKNOWN_MESSAGE = auto()
    SUCCESS = auto()
    FAILURE = auto()
    NO_ACTION = auto()


class TelegramNotifier:
    TELEGRAM_URL: str = "https://api.telegram.org/bot{api_token}/{method}"

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.ssm_client = boto3.client("ssm")
        self.api_token = self.ssm_client.get_parameter(
            Name=SSM_PATH_TELEGRAM_API_TOKEN, WithDecryption=True
        )["Parameter"]["Value"]
        self.chat_id = self.ssm_client.get_parameter(Name=SSM_PATH_TELEGRAM_CHAT_ID)[
            "Parameter"
        ]["Value"]

    def send(
        self,
        text: str,
        parse_mode="HTML",
        disable_web_page_preview=True,
        disable_notification=False,
    ) -> None:
        self.logger.debug(f"Sending:\n{text}")
        # https://core.telegram.org/bots/api#sendmessage
        response = requests.post(
            url=self.TELEGRAM_URL.format(
                api_token=self.api_token, method="sendmessage"
            ),
            data={
                "chat_id": self.chat_id,
                "parse_mode": parse_mode,
                "disable_web_page_preview": disable_web_page_preview,
                "disable_notification": disable_notification,
                "text": text,
            },
        )
        self.logger.debug(
            f"Sent message, response status: {response.status_code}\n{response.json()}"
        )
        response.raise_for_status()
        if disable_notification:
            self.send_chat_action()

    def send_chat_action(self, action="typing"):
        self.logger.debug(f"Sending chat action {action}")
        # https://core.telegram.org/bots/api#sendchataction
        response = requests.post(
            url=self.TELEGRAM_URL.format(
                api_token=self.api_token, method="sendchataction"
            ),
            data={
                "chat_id": self.chat_id,
                "action": action,
            },
        )
        self.logger.debug(
            f"Sent chat action, response status: {response.status_code}\n{response.json()}"
        )
        response.raise_for_status()


class Bouncer:
    """Handles initial invocation from Telegram's webhook:
    * Basic sanity check of incoming message
    * Validate chat id (only allow specific chat id)
    * Kick off state machine
    * Ackknowledge Telegram with 200 response, regardless of the outcome (required by Telegram's API)
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.sfn_client = boto3.client("stepfunctions")
        self.ssm_client = boto3.client("ssm")
        self.allowed_chat_id = self.ssm_client.get_parameter(
            Name=SSM_PATH_TELEGRAM_CHAT_ID
        )["Parameter"]["Value"]

    def _extract_incoming_message(self, event):
        return json.loads(event["body"])

    def _verify_chat_id(self, incoming_message):
        incoming_chat_id = str(incoming_message["message"]["chat"]["id"])
        if incoming_chat_id != self.allowed_chat_id:
            msg = f"Chat id '{incoming_chat_id}' not allowed."
            self.logger.info(msg)
            raise UnknownChatIdException(msg)

    def _create_payload(self, incoming_message):
        return {
            "message": {
                "sender": incoming_message["message"]["from"]["first_name"],
                "incoming_text": incoming_message["message"]["text"],
            }
        }

    def _start_state_machine(self, payload):
        response = self.sfn_client.start_execution(
            stateMachineArn=os.environ["STATE_MACHINE_ARN"], input=json.dumps(payload)
        )
        self.logger.info(f"Starting state machine: '{response['executionArn']}'")

    def _get_return_message(self, message, status_code=200):
        return {"statusCode": status_code, "body": json.dumps({"message": message})}

    def handle_event(self, event):
        try:
            incoming_message = self._extract_incoming_message(event)
            self._verify_chat_id(incoming_message)
            payload = self._create_payload(incoming_message)
            self._start_state_machine(payload)
            result = self._get_return_message(
                message="Event received, state machine started."
            )
        except UnknownChatIdException:
            # Swallow stack trace. Return 200 to acknowledge & prevent telegram from resending.
            result = self._get_return_message(message="403 - private bot")
        except Exception as e:
            logging.exception(e)
            # Return 200 to acknowledge & prevent telegram from resending.
            result = self._get_return_message(
                message=f"500 - error processing incoming event: {event}\n\n{e}",
            )
        return result


class Dispatcher:
    """Parses incomming message and returns result for dispatching."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.telegram = TelegramNotifier()

    def _send_telegram(self, message, response_text):
        self.telegram.send(
            text=f"Hello {message['sender']}, you said '{message['incoming_text']}'.\n\n{response_text}",
            disable_notification=True,
        )

    def _is_video_url(self, text):
        return text.startswith("https://youtu.be") or text.startswith(
            "https://www.youtube.com"
        )

    def _is_command(self, text):
        return text.startswith("/")

    def handle_event(self, payload):
        try:
            self.logger.info(f"{self.__class__.__name__} - called with {payload}")
            message = payload["message"]
            incoming_text = message["incoming_text"]
            if self._is_video_url(incoming_text):
                self._send_telegram(message, "...A video. 📽️")
                status = Status.DOWNLOADER
            elif self._is_command(incoming_text):
                self._send_telegram(message, "...A command. 🫡")
                status = Status.COMMANDER
            else:
                self._send_telegram(message, "...I'm not sure what to do with that.")
                status = Status.UNKNOWN_MESSAGE
        except Exception as e:
            logger.exception(e)
            self.telegram.send(f"⚠️ Error: '{str(e)}'")
            status = Status.FAILURE
        return dict(status=status.name, message=payload["message"])


class Commander:
    """Process commands"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.telegram = TelegramNotifier()
        self.storage_table_name = os.environ["STORAGE_TABLE_NAME"]
        self.storage_table = boto3.resource("dynamodb").Table(self.storage_table_name)

    def _cmd_list(self, command):
        now = time.time()
        result = ["...I found these entries:"]
        result.extend(
            [
                f"* <i>{episode['Title']}</i> (<pre>{episode['EpisodeId']}</pre>, <b>-{timedelta(seconds=int(now-int(episode['TimestampUtc'])))}</b>) "
                for episode in self._retrieve_metadata()
            ]
        )
        self.telegram.send(
            "\n".join(result),
            disable_notification=True,
        )

    def _cmd_help(self, command):
        self.telegram.send(
            textwrap.dedent(
                f"""\
                ...I understand these commands:
                <pre> {'/help':<20}</pre>This text.
                <pre> {'/list (n)':<20}</pre>List all (<i>last n</i>) entries in database.
                """
            ),
            disable_notification=True,
        )

    def _retrieve_metadata(self):
        items = self.storage_table.scan()["Items"]
        print(items)
        return items

    def handle_event(self, payload: dict):
        try:
            self.logger.info(f"{self.__class__.__name__} - called with {payload}")
            command = payload["message"]["incoming_text"]
            if command.startswith("/list"):
                self._cmd_list(command)
            elif command.startswith("/help"):
                self._cmd_help(command)
            status = Status.SUCCESS
        except Exception as e:
            logger.exception(e)
            self.telegram.send(f"⚠️ Error:\n{e}'")
            status = Status.FAILURE
        return dict(status=status.name, message=payload["message"])


class Downloader:
    """Downloads video from submitted URL, stores in S3 & DynamoDB"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.telegram = TelegramNotifier()
        self.storage_bucket_name = os.environ["STORAGE_BUCKET_NAME"]
        self.storage_bucket = boto3.resource("s3").Bucket(self.storage_bucket_name)
        self.storage_table_name = os.environ["STORAGE_TABLE_NAME"]
        self.storage_table = boto3.resource("dynamodb").Table(self.storage_table_name)

    def _populate_video_information(self, url: str):
        self.logger.info(f"Downloading video from {url}")
        yt = YouTube(url)
        return VideoInformation(
            video_id=yt.video_id,
            title=yt.title,
            author=yt.author,
            description=yt.description,
            thumbnail_url=yt.thumbnail_url,
            duration_in_seconds=yt.length,
            keywords=yt.keywords,
            source_url=url,
        )

    def _is_existing_video(self, video_information: VideoInformation):
        self.logger.info(f"Is this new? {video_information}")
        return self.storage_table.query(
            KeyConditionExpression=Key("EpisodeId").eq(video_information.video_id)
        )["Items"]

    def _download_audio_stream(self, video_information: VideoInformation) -> str:
        return (
            YouTube(video_information.source_url)
            .streams.filter(only_audio=True)
            .filter(subtype="mp4")
            .order_by("abr")
            .desc()
            .first()
            .download(output_path="/tmp", filename=f"{video_information.video_id}.mp4")
        )

    def _download_thumbnail(self, video_information: VideoInformation) -> str:
        url_without_query_string = video_information.thumbnail_url.split("?")[0]
        _, file_extension = os.path.splitext(url_without_query_string)
        return request.urlretrieve(
            url=video_information.thumbnail_url,
            filename=f"/tmp/{video_information.video_id}_logo{file_extension}",
        )[0]

    def _upload_to_s3(self, audio_file_path: str, thumbnail_file_path: str):
        audio_bucket_path = f"audio/default/{os.path.basename(audio_file_path)}"
        audio_file_size = Path(audio_file_path).stat().st_size
        self.storage_bucket.upload_file(audio_file_path, audio_bucket_path)

        thumbnail_bucket_path = f"audio/default/{os.path.basename(thumbnail_file_path)}"
        self.storage_bucket.upload_file(thumbnail_file_path, thumbnail_bucket_path)

        now = datetime.utcnow()
        return UploadInformation(
            path_to_episode=audio_bucket_path,
            path_to_thumbnail=thumbnail_bucket_path,
            timestamp_utc=int(now.timestamp()),
            timestamp_rfc822=email.utils.format_datetime(now),
            episode_size=audio_file_size,
        )

    def _create_cleansed_metadata(
        self,
        upload_information: UploadInformation,
        video_information: VideoInformation,
    ) -> dict:
        return dict(
            [
                ("CastId", "default"),
                ("EpisodeId", video_information.video_id),
                ("Title", video_information.title),
                ("Author", video_information.author),
                ("Description", video_information.description),
                ("DurationInSeconds", video_information.duration_in_seconds),
                ("Keywords", video_information.keywords[:250]),
                ("FileLengthInByte", upload_information.episode_size),
                ("BucketPathEpisode", upload_information.path_to_episode),
                ("BucketPathThumbnail", upload_information.path_to_thumbnail),
                ("TimestampUtc", str(upload_information.timestamp_utc)),
                ("TimestampRfc822", upload_information.timestamp_rfc822),
            ]
        )

    def _store_metadata(self, metadata: dict):
        self.storage_table.put_item(Item=metadata)
        logger.info(f"Storing metadata: {metadata}")

    def handle_event(self, payload):
        try:
            self.logger.info(f"{self.__class__.__name__} - called with {payload}")
            message = payload["message"]
            url = message["incoming_text"]
            video_information = self._populate_video_information(url)
            if not self._is_existing_video(video_information):
                start_time = time.time()
                audio_file_path = self._download_audio_stream(video_information)
                thumbnail_file_path = self._download_thumbnail(video_information)
                upload_information = self._upload_to_s3(
                    audio_file_path=audio_file_path,
                    thumbnail_file_path=thumbnail_file_path,
                )
                metadata = self._create_cleansed_metadata(
                    upload_information, video_information
                )
                self._store_metadata(metadata)
                total_time = int(time.time() - start_time)
                self.telegram.send(
                    f"""...Download finished, database updated:
                    \n<pre> Title: {video_information.title}\n Length: {timedelta(seconds=video_information.duration_in_seconds)}\n File Size: {upload_information.episode_size >> 20}MB\n Time to Download: {total_time}s</pre>
                    """,
                    disable_notification=True,
                )
                status = Status.SUCCESS
            else:
                self.telegram.send(
                    f"...'{video_information.title}' is already in your cast. Skipping download.",
                    disable_notification=True,
                )
                status = Status.NO_ACTION
        except Exception as e:
            logger.exception(e)
            self.telegram.send(f"⚠️ Error: '{str(e)}'")
            status = Status.FAILURE
        return dict(status=status.name, message=payload["message"])


class Podcaster:
    """Generates podcast feed and uploads to S3"""

    FEED_NAME = "default-feed.rss"

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.telegram = TelegramNotifier()
        self.storage_bucket_name = os.environ["STORAGE_BUCKET_NAME"]
        self.storage_bucket = boto3.resource("s3").Bucket(self.storage_bucket_name)
        self.storage_table_name = os.environ["STORAGE_TABLE_NAME"]
        self.storage_table = boto3.resource("dynamodb").Table(self.storage_table_name)
        self.base_url = f'https://{os.environ["DISTRIBUTION_DOMAIN_NAME"]}'
        self.feed_url = f"{self.base_url}/{self.FEED_NAME}"
        self.jinja_env = Environment(
            loader=PackageLoader("sauer"),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def _retrieve_metadata(self):
        items = self.storage_table.scan()["Items"]
        return items

    def _generate_rss_feed(self, metadata):
        template = self.jinja_env.get_template("podcast.xml.j2")
        output = template.render(
            dict(
                podcast=dict(
                    last_build_date=email.utils.format_datetime(datetime.now()),
                    base_url=self.base_url,
                    feed_url=f"{self.base_url}/{self.FEED_NAME}",
                    title="Sauerpod Cast",
                    episodes=metadata,
                )
            )
        )
        return output

    def _upload_to_s3(self, rss_feed):
        with tempfile.NamedTemporaryFile(mode="w") as tmp_file:
            tmp_file.write(rss_feed)
            tmp_file.flush()
            self.storage_bucket.upload_file(
                Filename=tmp_file.name,
                Key=self.FEED_NAME,
                ExtraArgs={"ContentType": "application/rss+xml"},
            )

    def handle_event(self, payload):
        try:
            self.logger.info(f"{self.__class__.__name__} - called with {payload}")
            metadata = self._retrieve_metadata()
            rss_feed = self._generate_rss_feed(metadata)
            self._upload_to_s3(rss_feed)
            self.telegram.send(
                f"""...Podcast feed generated and uploaded:
                \n <a href="{self.feed_url}">🎧 here 🎧</a>
                """,
                disable_notification=True,
            )
            status = Status.SUCCESS
        except Exception as e:
            logger.exception(e)
            self.telegram.send(f"⚠️ Error:\n{e}'")
            status = Status.FAILURE
        return dict(status=status.name, message=payload["message"])


class Finalizer:
    """Finalize interaction"""

    def handle_event(self, payload):
        try:
            self.logger.info(f"{self.__class__.__name__} - called with {payload}")
            status = Status.SUCCESS
        except Exception as e:
            logger.exception(e)
            self.telegram.send(f"⚠️ Error:\n{e}'")
            status = Status.FAILURE
        return dict(status=status.name, message=payload["message"])


@notify_cloudwatch
def bouncer_handler(event, context) -> dict:
    return Bouncer().handle_event(event)


@notify_cloudwatch
def dispatcher_handler(event, context) -> dict:
    return Dispatcher().handle_event(event)


@notify_cloudwatch
def commander_handler(event, context) -> dict:
    return Commander().handle_event(event)


@notify_cloudwatch
def downloader_handler(event, context) -> dict:
    return Downloader().handle_event(event)


@notify_cloudwatch
def podcaster_handler(event, context) -> dict:
    return Podcaster().handle_event(event)


@notify_cloudwatch
def _handler(event, context) -> dict:
    return Finalizer().handle_event(event)


if __name__ == "__main__":
    stack_outputs = boto3.client("cloudformation").describe_stacks(
        StackName="sauerpod-storage-stack"
    )["Stacks"][0]["Outputs"]
    bucket_name = next(
        output["OutputValue"]
        for output in stack_outputs
        if output["OutputKey"] == "StorageBucketName"
    )
    table_name = next(
        output["OutputValue"]
        for output in stack_outputs
        if output["OutputKey"] == "StorageTableName"
    )
    os.environ["STORAGE_TABLE_NAME"] = table_name
    os.environ["STORAGE_BUCKET_NAME"] = bucket_name
    event = dict(message=dict(incoming_text="/list 12"))
    Commander().handle_event(event)
