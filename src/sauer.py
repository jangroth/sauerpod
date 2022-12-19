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
from boto3.dynamodb.conditions import Attr, Key
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
Payload = namedtuple("Payload", ["sender_name", "incoming_text", "chat_id"])


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
    PODCASTER = auto()
    COMMANDER = auto()
    FINISH = auto()
    FAILURE = auto()


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
        disable_notification=True,
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
                "sender_name": incoming_message["message"]["from"]["first_name"],
                "incoming_text": incoming_message["message"]["text"],
                "chat_id": str(incoming_message["message"]["chat"]["id"]),
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

    def _send_telegram(self, sender_name, incoming_text, response_text):
        self.telegram.send(
            text=f"Hello {sender_name}, you said '{incoming_text}'.\n\n{response_text}",
        )

    def _is_video_url(self, text):
        return (
            text.startswith("https://youtu.be")
            or text.startswith("https://www.youtube.com")
            or text.startswith("https://youtube.com")
        )

    def _is_command(self, text):
        return text.startswith("/")

    def handle_event(self, event):
        try:
            self.logger.info(f"{self.__class__.__name__} - called with {event}")
            payload = Payload(**event["message"])
            if self._is_video_url(payload.incoming_text):
                status = Status.DOWNLOADER
            elif self._is_command(payload.incoming_text):
                status = Status.COMMANDER
            else:
                self.telegram.send(
                    text=f"Hello {payload.sender_name}, you said '{payload.incoming_text}'.\n\nI don't know what to do with that.",
                )
                status = Status.FINISH
        except Exception as e:
            logger.exception(e)
            self.telegram.send(f"⚠️ Error:\n{e}")
            status = Status.FAILURE
        return dict(status=status.name, message=event["message"])


class Commander:
    """Process commands"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.telegram = TelegramNotifier()
        self.storage_bucket_name = os.environ["STORAGE_BUCKET_NAME"]
        self.storage_bucket = boto3.resource("s3").Bucket(self.storage_bucket_name)
        self.storage_table_name = os.environ["STORAGE_TABLE_NAME"]
        self.storage_table = boto3.resource("dynamodb").Table(self.storage_table_name)
        self.base_url = f'https://{os.environ["DISTRIBUTION_DOMAIN_NAME"]}'

    def _convert_to_line_item(self, episode: dict, now: float, compact: bool) -> str:
        title = (
            (episode["Title"][:25] + "..")
            if len(episode["Title"]) > 27 and compact
            else episode["Title"]
        )
        age = timedelta(seconds=int(now - int(episode["TimestampUtc"])))
        episode_link = f"<a href='{self.base_url}/{episode['BucketPathEpisode']}'>{episode['EpisodeId']}</a>"
        return f"* <i>{title}</i> ({episode_link}, <b>-{age}</b>) "

    def _query_episodes(self, feed_id: str, ascending: bool, limit: int = None) -> dict:
        kwargs = {
            "KeyConditionExpression": Key("FeedId").eq(feed_id),
            "ScanIndexForward": ascending,
        }
        if limit:
            kwargs["Limit"] = limit
        return self.storage_table.query(**kwargs)["Items"]

    def _delete_episode(self, chat_id, episode_id) -> str:
        try:
            episode = next(
                episode
                for episode in self.storage_table.query(
                    KeyConditionExpression=Key("FeedId").eq(chat_id),
                    FilterExpression=Key("EpisodeId").eq(episode_id),
                )["Items"]
            )
            self.storage_bucket.delete_objects(
                Delete={"Objects": [{"Key": episode["BucketPathThumbnail"]}]}
            )
            self.storage_bucket.delete_objects(
                Delete={"Objects": [{"Key": episode["BucketPathEpisode"]}]}
            )
            self.storage_table.delete_item(
                Key={"FeedId": chat_id, "TimestampUtc": episode["TimestampUtc"]},
                ConditionExpression=Attr("EpisodeId").eq(episode_id),
            )
            result = f"Episode {episode_id} deleted."
        except StopIteration:
            result = f"Couldn't find episode <pre>{episode_id}</pre> in database. Is this the right id?"
        return result

    def _cmd_list(self, command, chat_id) -> None:
        now = time.time()
        result = [
            self._convert_to_line_item(episode, now, not command.endswith("full"))
            for episode in self._query_episodes(feed_id=chat_id, ascending=False)
        ]
        self.telegram.send("\n".join(result))

    def _cmd_delete(self, command, chat_id) -> bool:
        try:
            command_fragments = command.split()
            command_text = command_fragments[0]
            if command_text == "/deletenewest":
                episode_id = self._query_episodes(feed_id=chat_id, ascending=False)[0][
                    "EpisodeId"
                ]
            elif command_text == "/deleteoldest":
                episode_id = self._query_episodes(feed_id=chat_id, ascending=True)[0][
                    "EpisodeId"
                ]
            elif len(command_fragments) == 2:
                episode_id = command_fragments[1]
            else:
                raise ValueError()
            message = self._delete_episode(chat_id=chat_id, episode_id=episode_id)
            update_required = True
        except ValueError:
            message = f"I don't understand '{command}'."
            update_required = False
        self.telegram.send(message)
        return update_required

    def _cmd_help(self):
        self.telegram.send(
            textwrap.dedent(
                f"""\
                I understand these commands:
                <pre> {'/help':<20}</pre>This text.
                <pre> {'/list':<20}</pre>List entries in database (compact layout).
                <pre> {'/listfull':<20}</pre>List entries in database (full layout).
                <pre> {'/delete [id]':<20}</pre>Delete entry from database.
                <pre> {'/deletenewest':<20}</pre>Delete newest entry from database.
                <pre> {'/deleteoldest':<20}</pre>Delete oldest entry from database.
                """
            ),
        )

    def handle_event(self, event: dict):
        try:
            self.logger.info(f"{self.__class__.__name__} - called with {event}")
            payload = Payload(**event["message"])
            command = payload.incoming_text
            if command.startswith("/list"):
                self._cmd_list(command=command, chat_id=payload.chat_id)
                status = Status.FINISH
            if command.startswith("/delete"):
                update_required = self._cmd_delete(
                    command=command, chat_id=payload.chat_id
                )
                status = Status.PODCASTER if update_required else Status.FINISH
            elif command.startswith("/help"):
                self._cmd_help()
                status = Status.FINISH
        except Exception as e:
            logger.exception(e)
            self.telegram.send(f"⚠️ Error:\n{e}")
            status = Status.FAILURE
        return dict(status=status.name, message=event["message"])


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

    def _is_existing_video(self, video_information: VideoInformation, chat_id: str):
        self.logger.info(f"Is this new? {video_information}")
        return self.storage_table.query(
            KeyConditionExpression=Key("FeedId").eq(chat_id),
            FilterExpression=Attr("EpisodeId").eq(video_information.video_id),
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

    def _upload_to_s3(
        self, chat_id: str, audio_file_path: str, thumbnail_file_path: str
    ):
        audio_bucket_path = f"audio/{chat_id}/{os.path.basename(audio_file_path)}"
        audio_file_size = Path(audio_file_path).stat().st_size
        self.storage_bucket.upload_file(audio_file_path, audio_bucket_path)

        thumbnail_bucket_path = (
            f"audio/{chat_id}/{os.path.basename(thumbnail_file_path)}"
        )
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
        chat_id: str,
        upload_information: UploadInformation,
        video_information: VideoInformation,
    ) -> dict:
        return dict(
            [
                ("FeedId", chat_id),
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

    def handle_event(self, event):
        try:
            self.logger.info(f"{self.__class__.__name__} - called with {event}")
            payload = Payload(**event["message"])
            video_information = self._populate_video_information(payload.incoming_text)
            if not self._is_existing_video(video_information, payload.chat_id):
                self.telegram.send("...Downloading video.")
                audio_file_path = self._download_audio_stream(video_information)
                thumbnail_file_path = self._download_thumbnail(video_information)
                upload_information = self._upload_to_s3(
                    chat_id=payload.chat_id,
                    audio_file_path=audio_file_path,
                    thumbnail_file_path=thumbnail_file_path,
                )
                metadata = self._create_cleansed_metadata(
                    chat_id=payload.chat_id,
                    upload_information=upload_information,
                    video_information=video_information,
                )
                self._store_metadata(metadata)
                status = Status.PODCASTER
            else:
                self.telegram.send(
                    f"...'{video_information.title}' is already in your cast. Skipping download.",
                )
                status = Status.FINISH
        except Exception as e:
            logger.exception(e)
            self.telegram.send(f"⚠️ Error:\n{e}")
            status = Status.FAILURE
        return dict(status=status.name, message=event["message"])


class Podcaster:
    """Generates podcast feed and uploads to S3"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.telegram = TelegramNotifier()
        self.storage_bucket_name = os.environ["STORAGE_BUCKET_NAME"]
        self.storage_bucket = boto3.resource("s3").Bucket(self.storage_bucket_name)
        self.storage_table_name = os.environ["STORAGE_TABLE_NAME"]
        self.storage_table = boto3.resource("dynamodb").Table(self.storage_table_name)
        self.base_url = f'https://{os.environ["DISTRIBUTION_DOMAIN_NAME"]}'
        self.jinja_env = Environment(
            loader=PackageLoader("sauer"),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def _retrieve_metadata(self, chat_id):
        return self.storage_table.query(
            KeyConditionExpression=Key("FeedId").eq(chat_id), ScanIndexForward=False
        )["Items"]

    def _generate_rss_feed(self, metadata, feed_name):
        template = self.jinja_env.get_template("podcast.xml.j2")
        output = template.render(
            dict(
                podcast=dict(
                    last_build_date=email.utils.format_datetime(datetime.now()),
                    base_url=self.base_url,
                    feed_url=f"{self.base_url}/{feed_name}",
                    title="Sauerpod Cast",
                    episodes=metadata,
                )
            )
        )
        return output

    def _upload_to_s3(self, feed_name: str, feed_content: str):
        with tempfile.NamedTemporaryFile(mode="w") as tmp_file:
            tmp_file.write(feed_content)
            tmp_file.flush()
            self.storage_bucket.upload_file(
                Filename=tmp_file.name,
                Key=feed_name,
                ExtraArgs={"ContentType": "application/rss+xml"},
            )

    def handle_event(self, event):
        try:
            self.logger.info(f"{self.__class__.__name__} - called with {event}")
            payload = Payload(**event["message"])
            metadata = self._retrieve_metadata(payload.chat_id)
            feed_name = f"{payload.chat_id}.rss"
            feed_url = f"{self.base_url}/{feed_name}"
            feed_content = self._generate_rss_feed(metadata, feed_name)
            self._upload_to_s3(feed_name, feed_content)
            self.telegram.send(
                f"""...Podcast feed generated and uploaded:
                \n <a href="{feed_url}">🎧 {feed_url} 🎧</a>
                """,
            )
            status = Status.FINISH
        except Exception as e:
            logger.exception(e)
            self.telegram.send(f"⚠️ Error:\n{e}")
            status = Status.FAILURE
        return dict(status=status.name, message=event["message"])


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


if __name__ == "__main__":
    stack_outputs = boto3.client("cloudformation").describe_stacks(
        StackName="sauerpod-storage-stack"
    )["Stacks"][0]["Outputs"]
    bucket_name = next(
        output["OutputValue"]
        for output in stack_outputs
        if output["OutputKey"] == "StorageBucketNameCfn"
    )
    table_name = next(
        output["OutputValue"]
        for output in stack_outputs
        if output["OutputKey"] == "StorageTableNameCfn"
    )
    stack_outputs = boto3.client("cloudformation").describe_stacks(
        StackName="sauerpod-publish-stack"
    )["Stacks"][0]["Outputs"]
    domain_name = next(
        output["OutputValue"]
        for output in stack_outputs
        if output["OutputKey"] == "DistributionDomainNameCfn"
    )
    os.environ["STORAGE_TABLE_NAME"] = table_name
    os.environ["STORAGE_BUCKET_NAME"] = bucket_name
    os.environ["DISTRIBUTION_DOMAIN_NAME"] = domain_name
    event = dict(
        message=dict(
            sender_name="foo",
            incoming_text="/deletefirst",
            chat_id="173229021",
        )
    )
    payload = Payload(**event["message"])
    Commander().handle_event(event)
