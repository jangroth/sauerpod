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
    "message": {
        "message_id": 14,
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


@pytest.fixture
def good_event():
    event = json.loads(BASE_EVENT)
    event["body"] = BASE_MESSAGE
    return event


@pytest.fixture
def bad_event():
    event = json.loads(BASE_EVENT)
    event["foo"] = "bar"
    return event


@pytest.fixture()
def bouncer():
    the_object = Bouncer.__new__(Bouncer)
    the_object.logger = MagicMock()
    the_object.telegram = MagicMock()
    return the_object


def test_should_process_good_event_and_start_state_machine(good_event, bouncer):
    bouncer._start_state_machine = MagicMock()

    result = bouncer.handle_event(good_event)

    bouncer._start_state_machine.assert_called_once_with(json.loads(BASE_MESSAGE))
    assert result["statusCode"] == 200


def test_return_500_on_bad_event(bad_event, bouncer):
    bouncer._start_state_machine = MagicMock()

    result = bouncer.handle_event(good_event)

    bouncer._start_state_machine.assert_not_called()
    assert result["statusCode"] == 500
