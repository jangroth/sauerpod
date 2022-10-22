import json
from unittest.mock import MagicMock

import pytest
from sauer import Bouncer

BASE_EVENT = """
{
    "version": "2.0",
    "headers": {
        "content-length": "307"
    },
    "requestContext": {
        "accountId": "anonymous",
        "http": {
            "method": "POST",
            "path": "/",
            "protocol": "HTTP/1.1",
            "sourceIp": "91.108.6.94"
        },
        "requestId": "822a0076-68b1-4043-af72-0f38df47d327",
        "routeKey": "$default",
        "stage": "$default",
        "time": "10/May/2022:10:35:02 +0000",
        "timeEpoch": 1652178902114
    },
    "isBase64Encoded": false
}
"""
BASE_MESSAGE = """
{
    "update_id": 58754382,
    "message_id": 14,
    "message": {
        "from": {
            "id": 123456789,
            "is_bot": "False",
            "first_name": "first_name",
            "last_name": "last_name",
            "username": "username",
            "language_code": "en"
        },
        "chat": {
            "id": 123456789,
            "first_name": "first_name",
            "last_name": "last_name",
            "username": "username",
            "type": "private"
        },
        "date": 1652178739,
        "text": "yoman"
    }
}
"""
PAYLOAD = """
{
    "incoming_text": "yoman",
    "sender": "first_name"
}
"""

CHAT_ID_ALLOWED = "123456789"
CHAT_ID_FORBIDDEN = "111111111"


@pytest.fixture
def good_event():
    event = json.loads(BASE_EVENT)
    base_message_json = json.loads(BASE_MESSAGE)
    event["body"] = json.dumps(base_message_json)
    return event


@pytest.fixture
def good_event_bad_chat():
    event = json.loads(BASE_EVENT)
    base_message_json = json.loads(BASE_MESSAGE)
    base_message_json["message"]["chat"]["id"] = CHAT_ID_FORBIDDEN
    event["body"] = json.dumps(base_message_json)
    return event


@pytest.fixture
def bad_event():
    event = json.loads(BASE_EVENT)
    event["foo"] = "bar"
    return event


@pytest.fixture()
def bouncer():
    the_object = Bouncer.__new__(Bouncer)
    the_object.sfn_client = MagicMock()
    the_object.logger = MagicMock()
    the_object.bot = MagicMock()
    the_object.allowed_chat_id = CHAT_ID_ALLOWED
    return the_object


def test_should_process_good_event_and_start_state_machine(good_event, bouncer):
    bouncer._start_state_machine = MagicMock()

    result = bouncer.handle_event(good_event)

    bouncer._start_state_machine.assert_called_once_with(json.loads(PAYLOAD))
    assert result["statusCode"] == 200
    assert result["body"] == json.dumps(
        {"message": "Event received, state machine started."}
    )


def test_return_error_message_on_bad_event(bad_event, bouncer):
    bouncer._start_state_machine = MagicMock()

    result = bouncer.handle_event(bad_event)

    bouncer._start_state_machine.assert_not_called()
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["message"].startswith(
        "500 - error processing incoming event:"
    )


def test_should_return_privacy_message_on_bad_chat_id(good_event_bad_chat, bouncer):
    bouncer._acknowledge = MagicMock()
    bouncer._start_state_machine = MagicMock()

    result = bouncer.handle_event(good_event_bad_chat)

    bouncer._acknowledge.assert_not_called()
    bouncer._start_state_machine.assert_not_called()
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["message"].startswith("403 - private bot")


def test_should_extract_payload_from_incoming_message(good_event, bouncer):
    event_body = bouncer._extract_incoming_message(good_event)

    result = bouncer._create_payload(event_body)

    assert result == json.loads(PAYLOAD)
