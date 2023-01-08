from collections import namedtuple
from enum import Enum, auto
import boto3
import logging
import requests
import os

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("common")
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


class Status(Enum):
    DOWNLOADER = auto()
    PODCASTER = auto()
    COMMANDER = auto()
    FINISH = auto()
    FAILURE = auto()


class UnknownChatIdException(Exception):
    pass


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


def notify_cloudwatch(function):
    def wrapper(*args, **kwargs):
        incoming_event = args[0]  # ...event
        function_name = args[1].function_name
        logger.info(f"'{function_name}' - entry.\nIncoming event: '{incoming_event}'")
        result = function(*args, **kwargs)
        logger.info(f"'{function_name}' - exit.\n\nResult: '{result}'")
        return result

    return wrapper
