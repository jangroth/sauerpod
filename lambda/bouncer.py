import json
import logging
import os

import boto3
import requests

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("RevokeDefaultSgApplication")
logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))


class TelegramNotifier:
    TELEGRAM_URL = "https://api.telegram.org/bot{api_token}/sendMessage?chat_id={chat_id}&parse_mode=HTML&text={message}"

    def __init__(self):
        ssm_client = boto3.client("ssm")
        self.api_token = ssm_client.get_parameter(
            Name="/pycast/telegram/api-token", WithDecryption=True
        )["Parameter"]["Value"]
        self.chat_id = ssm_client.get_parameter(Name="/pycast/telegram/chat-id")[
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


def handler(event, context):
    logger.info(f"Incoming request: {json.dumps(event)}")
    request_method = event["requestContext"]["http"]["method"]
    request_path = event["requestContext"]["http"]["path"]
    request_body = event["body"]

    TelegramNotifier().send(request_body.get("message", "hey there!"))

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/plain"},
        "body": f"-> '{request_method}' to '{request_path}'\n{request_body}",
    }
