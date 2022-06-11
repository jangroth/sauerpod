import json
import logging
import os

import boto3
import telegram

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("SauerPod")
logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))


def notify_cloudwatch(function):
    def wrapper(*args, **kwargs):
        incoming_event = args[0]  # ...event
        function_name = args[1].function_name  # ...context
        logger.info(f"'{function_name}' - entry.\nIncoming event: '{incoming_event}'")
        result = function(*args, **kwargs)
        logger.info(f"'{function_name}' - exit.\n\nResult: '{result}'")
        return result

    return wrapper


class TelegramBot:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        ssm_client = boto3.client("ssm")
        self.API_TOKEN = ssm_client.get_parameter(
            Name="/sauerpod/telegram/api-token", WithDecryption=True
        )["Parameter"]["Value"]
        self.CHAT_ID = ssm_client.get_parameter(Name="/sauerpod/telegram/chat-id")[
            "Parameter"
        ]["Value"]
        self.bot = telegram.Bot(self.api_token)

    def send(self, message):
        self.bot.send_message(text=message, chat_id=self.chat_id)


class UnknownChatIdException(Exception):
    pass


class Bouncer:
    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.sfn_client = boto3.client("stepfunctions")
        self.bot = TelegramBot()
        self.ALLOWED_CHAT_ID = self.bot.CHAT_ID

    def _extract_incoming_message(self, event):
        return json.loads(event["body"])

    def _verify_chat_id(self, incoming_message):
        incoming_chat_id = str(incoming_message["message"]["chat"]["id"])
        if incoming_chat_id != self.ALLOWED_CHAT_ID:
            msg = f"Chat id '{incoming_chat_id}' not allowed."
            self.logger.info(msg)
            raise UnknownChatIdException(msg)

    def _acknowledge_message(self, incoming_message):
        first_name = incoming_message["message"]["from"]["first_name"]
        message = incoming_message["message"]["text"]
        self.bot.send(f"Hello {first_name}, you said '{message}'.")

    def _start_state_machine(self, message):
        # response = self.sfn_client.start_execution(
        #     stateMachineArn=os.environ["STATE_MACHINE_ARN"], input=json.dumps(message)
        # )
        # self.logger.info(response)
        # self.logger.info(f"Starting state machine: '{response['executionArn']}'")
        self.logger.info("NOT STARTING STATE MACHINE")

    def _get_return_message(self, status_code, message):
        return {
            "statusCode": status_code,
            "body": json.dumps({"message": message}),
        }

    def handle_event(self, event):
        try:
            event_body = self._extract_incoming_message(event)
            self._verify_chat_id(event_body)
            self._acknowledge_message(event_body)
            self._start_state_machine(event_body)
            result = self._get_return_message(
                status_code=200, message="Event received, state machine started."
            )
        except UnknownChatIdException:
            # Swallow stack trace. Return 200 to acknowledge & prevent telegram from resending.
            result = self._get_return_message(
                status_code=200, message="403 - private bot"
            )
        except Exception as e:
            logging.exception(e)
            # Return 200 to acknowledge & prevent telegram from resending.
            result = self._get_return_message(
                status_code=200,
                message=f"500 - error processing incoming event: {event}\n\n{e}",
            )
        self.logger.info(f"returning {result}")
        return result


@notify_cloudwatch
def bouncer_handler(event, context):
    try:
        result = Bouncer().handle_event(event)
    except Exception as e:
        logging.exception(e)
    return result


# EOF
