import json
import logging
import os

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("RevokeDefaultSgApplication")
logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))


def handler(event, context):
    logger.info(f"Incoming request: {json.dumps(event)}")
    request_method = event["requestContext"]["http"]["method"]
    request_path = event["requestContext"]["http"]["path"]
    request_body = event["body"]

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/plain"},
        "body": f"-> '{request_method}' to '{request_path}'\n{request_body}",
    }
