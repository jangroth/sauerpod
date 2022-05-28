import json
import logging
import os

import boto3
import requests

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("SauerPod")
logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))


class TelegramNotifier:
    TELEGRAM_URL = "https://api.telegram.org/bot{api_token}/sendMessage?chat_id={chat_id}&parse_mode=HTML&text={message}"

    def __init__(self):
        ssm_client = boto3.client("ssm")
        self.api_token = ssm_client.get_parameter(
            Name="/sauerpod/telegram/api-token", WithDecryption=True
        )["Parameter"]["Value"]
        self.chat_id = ssm_client.get_parameter(Name="/sauerpod/telegram/chat-id")[
            "Parameter"
        ]["Value"]

    def send(self, message):
        response = requests.get(
            self.TELEGRAM_URL.format(
                api_token=self.api_token, chat_id=self.chat_id, message=message
            )
        )
        if response.status_code != 200:
            raise ValueError(
                f"Request to Telegram returned an error {response.status_code}, the response is:\n{response.text}"
            )

    def notify_entry(self, context=None):
        self.send(f"<b>ENTRY</b> <i>{context.function_name}</i>")

    def notify_exit(self, context=None, status="NOT SUBMITTED"):
        self.send(
            f"<b>EXIT</b> - <i>{context.function_name}</i>\n\n<pre>Status: '{status}'</pre>"
        )


def notify_cloudwatch(function):
    def wrapper(*args, **kwargs):
        incoming_event = args[0]  # ...event
        function_name = args[1].function_name  # ...context
        logger.info(f"'{function_name}' - entry.\nIncoming event: '{incoming_event}'")
        result = function(*args, **kwargs)
        logger.info(f"'{function_name}' - exit.\n\nResult: '{result}'")
        return result

    return wrapper


class Bouncer:
    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.telegram = TelegramNotifier()

    def _extract_incoming_message(self, event):
        return json.loads(event["body"])

    def _acknowledge(self, incoming_message):
        first_name = incoming_message["message"]["from"]["first_name"]
        text = incoming_message["message"]["text"]
        self.telegram.send(f"Hello {first_name}, you said '{text}'.")

    def _start_state_machine(self, message):
        pass
        # response = self.sfn_client.start_execution(
        #     stateMachineArn=os.environ.get('STATE_MACHINE', None),
        #     input=json.dumps(message)
        # )
        # logging.info(f"Starting state machine: '{response['executionArn']}'")

    def _get_return_message(self, status_code, message):
        return {
            "statusCode": status_code,
            "body": json.dumps({"message": message}),
        }

    def handle_event(self, event):
        try:
            event_body = self._extract_incoming_message(event)
            self._acknowledge(event_body)
            self._start_state_machine(event_body)
            result = self._get_return_message(
                status_code=200, message="Event received, state machine started."
            )
            self.telegram.send("Event received, starting processing.")
        except Exception as e:
            logging.exception(e)
            result = self._get_return_message(
                status_code=500,
                message=f"Error processing incoming event {event}\n\n{e}",
            )
        return result


@notify_cloudwatch
def bouncer_handler(event, context):
    return Bouncer().handle_event(event)


# EOF
