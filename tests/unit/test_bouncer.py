import json
import sys
from unittest.mock import MagicMock

import pytest
from sauer import Bouncer

BASE_EVENT = """
{
  "resource": "/video",
  "headers": {
    "Accept": "*/*"
  },
  "multiValueHeaders": {
    "Accept": [
      "*/*"
    ]
  },
  "requestContext": {
    "resourceId": "am7t8d"
  },
  "apiId": "chw6q7n9oc"
}
"""

BASE_MESSAGE = """
{
    "update_id": 58754382,
    "message": {
        "message_id": 14,
        "from": {
            "id": 123456789,
            "is_bot": False,
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
    event["body"] = json.dumps(BASE_MESSAGE)
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

    bouncer._start_state_machine.assert_called_once_with({"url": "https://www.ccc.de"})
    assert result["statusCode"] == 200


def test_return_500_on_bad_event(bad_event, bouncer):
    bouncer._start_state_machine = MagicMock()

    result = bouncer.handle_event(good_event)

    bouncer._start_state_machine.assert_not_called()
    assert result["statusCode"] == 500
