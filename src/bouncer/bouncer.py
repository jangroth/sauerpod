import boto3
import json
import logging
import os
from common import (
    notify_cloudwatch,
    UnknownChatIdException,
    SSM_PATH_TELEGRAM_CHAT_ID,
)

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
            self.logger.exception(e)
            # Return 200 to acknowledge & prevent telegram from resending.
            result = self._get_return_message(
                message=f"500 - error processing incoming event: {event}\n\n{e}",
            )
        return result


@notify_cloudwatch
def bouncer_handler(event, context) -> dict:
    return Bouncer().handle_event(event)
