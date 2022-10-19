import json
import logging
import os

import boto3
import requests

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("SauerPod")
logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))


SSM_PATH_TELEGRAM_API_TOKEN = "/sauerpod/telegram/api-token"
SSM_PATH_TELEGRAM_CHAT_ID = "/sauerpod/telegram/chat-id"

STATUS_SUCCESS = "SUCCESS"
STATUS_FAILURE = "FAILURE"
STATUS_DOWNLOADER = "DOWNLOADER"
STATUS_UNKNOWN_MESSAGE = "UNKNOWN_MESSAGE"


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
    TELEGRAM_URL: str = "https://api.telegram.org/bot{api_token}/sendMessage?chat_id={chat_id}&parse_mode=HTML&text={message}"  # https://core.telegram.org/bots/faq#how-can-i-make-requests-in-response-to-updates

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

    def send(self, message: dict) -> None:
        response = requests.get(
            self.TELEGRAM_URL.format(
                api_token=self.api_token, chat_id=self.chat_id, message=message
            )
        )
        self.logger.debug(f"Sent message, received: {response.content}")
        if response.status_code != 200:
            raise ValueError(
                f"Request to Telegram returned error {response.status_code}, the complete response is:\n{response.text}"
            )


class Bouncer:
    """Handles initial invocation from Telegram's webhook:
    * Basic sanity check of incoming message
    * Validate chat id (only allow specific chat id)
    * Kick off state machine (if checks path)
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

    def _start_state_machine(self, message):
        response = self.sfn_client.start_execution(
            stateMachineArn=os.environ["STATE_MACHINE_ARN"], input=json.dumps(message)
        )
        self.logger.info(f"Starting state machine: '{response['executionArn']}'")

    def _get_return_message(self, message, status_code=200):
        return {"statusCode": status_code, "body": json.dumps({"message": message})}

    def handle_event(self, event):
        try:
            event_body = self._extract_incoming_message(event)
            self._verify_chat_id(event_body)
            self._start_state_machine(event_body)
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

    def _get_return_message(self, status, event):
        return {"status": status, "event": event}

    def _acknowledge_message(self, incoming_message):
        first_name = incoming_message["message"]["from"]["first_name"]
        message = incoming_message["message"]["text"]
        self.telegram.send(
            f"Hello {first_name}, you said '{message}'.\nI'm not sure what to do with that."
        )

    def _is_video_url(self, message):
        return message.startswith("https://youtu.be")

    def handle_event(self, event):
        result = None
        self.logger.info(f"Dispatcher - called with {event}")
        incoming_message = event["message"]["text"]
        if self._is_video_url(incoming_message):
            result = self._get_return_message(STATUS_DOWNLOADER, event)
        else:
            self._acknowledge_message(event)
            result = self._get_return_message(STATUS_UNKNOWN_MESSAGE, event)
        return result


class Downloader:
    """Downloads video from submitted URL, stores in S3 & DynamoDB"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.telegram = TelegramNotifier()

    def _get_return_message(self, status, event):
        return {"status": status, "event": event}

    def handle_event(self, event):
        self.logger.info(f"Downloader - called with {event}")
        self.telegram.send(f"Hello from downloader! {event}")
        return self._get_return_message(STATUS_SUCCESS, event)


@notify_cloudwatch
def bouncer_handler(event, context) -> dict:
    try:
        result = Bouncer().handle_event(event)
    except Exception as e:
        logging.exception(e)
    return result


@notify_cloudwatch
def dispatcher_handler(event, context) -> dict:
    try:
        result = Dispatcher().handle_event(event)
    except Exception as e:
        logging.exception(e)
    return result


@notify_cloudwatch
def downloaderr_handler(event, context) -> dict:
    try:
        result = Downloader().handle_event(event)
    except Exception as e:
        logging.exception(e)
    return result


# EOF - `cdk watch` complains about missing EOF otherwise
