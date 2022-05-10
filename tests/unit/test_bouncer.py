import json
from unittest.mock import MagicMock

import pytest
from bouncer import Bouncer

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


@pytest.fixture
def good_event():
    event = json.loads(BASE_EVENT)
    event["body"] = '{"url":"https://www.ccc.de"}'
    return event


@pytest.fixture
def bad_event():
    event = json.loads(BASE_EVENT)
    event["foo"] = "bar"
    return event


@pytest.fixture()
def bnc():
    the_object = Bouncer.__new__(Bouncer)
    the_object.logger = MagicMock()
    the_object.telegram = MagicMock()
    return the_object


def test_should_process_good_event_and_start_state_machine(good_event, bnc):
    bnc._start_state_machine = MagicMock()

    result = bnc.handle_event(good_event)

    bnc._start_state_machine.assert_called_once_with({"url": "https://www.ccc.de"})
    assert result["statusCode"] == 200
