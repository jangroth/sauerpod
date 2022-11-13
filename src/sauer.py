import html
import json
import logging
import os
import time
from collections import namedtuple
from datetime import datetime
from pathlib import Path

import boto3
import requests
from boto3.dynamodb.conditions import Key
from pytube import YouTube

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("SauerPod")
logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))


SSM_PATH_TELEGRAM_API_TOKEN = "/sauerpod/telegram/api-token"
SSM_PATH_TELEGRAM_CHAT_ID = "/sauerpod/telegram/chat-id"
STATUS_DOWNLOADER = "FORWARD_TO_DOWNLOADER"
STATUS_UNKNOWN_MESSAGE = "UNKNOWN_MESSAGE"
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILURE = "FAILURE"
STATUS_NO_ACTION = "NO_ACTION"

VideoInformation = namedtuple(
    "VideoInformation",
    ["video_id", "title", "views", "rating", "description", "source_url"],
)
UploadInformation = namedtuple(
    "UploadInformation", ["bucket_path", "timestamp_utc", "file_size"]
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


class TelegramNotifier:
    TELEGRAM_URL: str = "https://api.telegram.org/bot{api_token}/sendMessage"

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
        disable_web_page_preview="True",
        disable_notification="False",
    ) -> None:
        self.logger.debug(f"Sending:\n{text}")
        # https://core.telegram.org/bots/api#sendmessage
        response = requests.post(
            url=self.TELEGRAM_URL.format(
                api_token=self.api_token,
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
        self.logger.info(f"Bouncer - returning {result}")
        return result


class Dispatcher:
    """Parses incomming message and returns result for dispatching."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.telegram = TelegramNotifier()

    def _get_return_message(self, status, payload):
        return {"status": status, "message": payload["message"]}

    def _send_telegram(self, message, response_text):
        self.telegram.send(
            text=f"Hello {message['sender']}, you said '{message['incoming_text']}'.\n\n{response_text}"
        )

    def _is_video_url(self, text):
        return text.startswith("https://youtu.be") or text.startswith(
            "https://www.youtube.com"
        )

    def handle_event(self, payload):
        self.logger.info(f"Dispatcher - called with {payload}")
        message = payload["message"]
        if self._is_video_url(message["incoming_text"]):
            self._send_telegram(message, "...A video. I got this.")
            result = self._get_return_message(STATUS_DOWNLOADER, payload)
        else:
            self._send_telegram(message, "...I'm not sure what to do with that.")
            result = self._get_return_message(STATUS_UNKNOWN_MESSAGE, payload)
        return result


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

    def _populate_video_information(self, url):
        self.logger.info(f"Downloading video from {url}")
        yt = YouTube(url)
        return VideoInformation(
            video_id=yt.video_id,
            title=yt.title,
            views=yt.views,
            rating=yt.rating,
            description=yt.description.encode("ascii", errors="ignore").decode(),
            source_url=url,
        )

    def _is_existing_video(self, video_information):
        self.logger.info(f"Is this new? {video_information}")
        return self.storage_table.query(
            KeyConditionExpression=Key("EpisodeId").eq(video_information.video_id)
        )["Items"]

    def _download_to_tmp(self, video_information):
        return (
            YouTube(video_information.source_url)
            .streams.filter(only_audio=True)
            .filter(subtype="mp4")
            .order_by("abr")
            .desc()
            .first()
            .download(output_path="/tmp", filename=f"{video_information.video_id}.mp4")
        )

    def _upload_to_s3(self, local_file_path, video_information):
        file_name = os.path.basename(local_file_path)
        bucket_path = f"audio/default/{file_name}"
        self.storage_bucket.upload_file(local_file_path, bucket_path)
        file_size = Path(local_file_path).stat().st_size
        return UploadInformation(
            bucket_path=bucket_path,
            timestamp_utc=int(datetime.utcnow().timestamp()),
            file_size=file_size,
        )

    def _store_metadata(self, download_information, video_information):
        metadata = dict(
            [
                ("CastId", "default"),
                ("EpisodeId", video_information.video_id),
                ("Title", video_information.title),
                ("Views", video_information.views),
                ("Rating", str(video_information.rating)),
                ("Description", video_information.description),
                ("BucketPath", download_information.bucket_path),
                ("TimestampUtc", str(download_information.timestamp_utc)),
            ]
        )
        self.storage_table.put_item(Item=metadata)
        logger.info(f"Storing metadata: {metadata}")

    def _get_return_message(self, status, payload):
        return {"status": status, "message": payload["message"]}

    def handle_event(self, payload):
        try:
            self.logger.info(f"Downloader - called with {payload}")
            message = payload["message"]
            url = message["incoming_text"]
            video_information = self._populate_video_information(url)
            if not self._is_existing_video(video_information):
                start_time = time.time()
                local_file_path = self._download_to_tmp(video_information)
                upload_information = self._upload_to_s3(
                    local_file_path, video_information
                )
                self._store_metadata(upload_information, video_information)
                total_time = int(time.time() - start_time)
                self.telegram.send(
                    f"...Download finished, database updated:\n<pre> Title: {video_information.title}\n File Size: {upload_information.file_size >> 20}MB\n Download time: {total_time}s</pre>"
                )
                status = "SUCCESS"
            else:
                self.telegram.send(
                    f"...'{video_information.title}' is already in your cast. Skipping download."
                )
                status = "NO_ACTION"
        except Exception as e:
            logger.exception(e)
            status = "FAILURE"
        return self._get_return_message(status, payload)


class Podcaster:
    """Updates podcast feed"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.telegram = TelegramNotifier()
        self.storage_bucket_name = os.environ["STORAGE_BUCKET_NAME"]
        self.storage_bucket = boto3.resource("s3").Bucket(self.storage_bucket_name)
        self.storage_table_name = os.environ["STORAGE_TABLE_NAME"]
        self.storage_table = boto3.resource("dynamodb").Table(self.storage_table_name)

    def _get_return_message(self, status, payload):
        return {"status": status, "message": payload["message"]}

    def handle_event(self, payload):
        try:
            self.logger.info(f"Podcater - called with {payload}")
            self.telegram.send("...Updating podcast")
            status = "SUCCESS"
        except Exception as e:
            logger.exception(e)
            status = "FAILURE"
        return self._get_return_message(status, payload)


@notify_cloudwatch
def bouncer_handler(event, context) -> dict:
    try:
        result = Bouncer().handle_event(event)
    except Exception as e:
        logging.exception(e)
        TelegramNotifier().send(f"⚠️ {str(e)}")
    return result


@notify_cloudwatch
def dispatcher_handler(event, context) -> dict:
    try:
        result = Dispatcher().handle_event(event)
    except Exception as e:
        logging.exception(e)
        TelegramNotifier().send(f"⚠️ {str(e)}")
    return result


@notify_cloudwatch
def downloader_handler(event, context) -> dict:
    try:
        result = Downloader().handle_event(event)
    except Exception as e:
        logging.exception(e)
        TelegramNotifier().send(f"⚠️ {str(e)}")
    return result


@notify_cloudwatch
def podcaster_handler(event, context) -> dict:
    try:
        result = Podcaster().handle_event(event)
    except Exception as e:
        logging.exception(e)
        TelegramNotifier().send(str(e))
    return result


if __name__ == "__main__":
    stack_outputs = boto3.client("cloudformation").describe_stacks(
        StackName="sauerpod-long-lived"
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
    event = dict(message=dict(incoming_text="https://youtu.be/dW2utwg9oOg"))
    Downloader().handle_event(event)
