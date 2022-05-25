import json
import logging
import os

import boto3

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("MyLambda")
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


class MyLambda:
    def __init__(self) -> None:
        self.sfn_client = boto3.client("stepfunctions")  # or other clients
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))

    def _extract_incoming_message(self, event):
        return json.loads(event["body"])

    def _do_something(self, message):
        pass

    def _get_return_message(self, status_code, message):
        return {
            "statusCode": status_code,
            "body": json.dumps({"message": message}),
        }

    def handle_event(self, event):
        try:
            event_body = self._extract_incoming_message(event)
            self._do_something(event_body)
            result = self._get_return_message(
                status_code=200, message="Event processed."
            )
        except Exception as e:
            logging.exception(e)
            result = self._get_return_message(
                status_code=500,
                message=f"Error processing incoming event {event}\n\n{e}",
            )
        return result


@notify_cloudwatch
def mylambda_handler(event, context):
    return MyLambda().handle_event(event)
