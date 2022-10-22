import json
from unittest.mock import MagicMock

import pytest
from sauer import STATUS_DOWNLOADER, STATUS_UNKNOWN_MESSAGE, Dispatcher

BASE_PAYLOAD = """
{
    "incoming_text": "yoman",
    "sender": "first_name"
}
"""

PAYLOAD_VIDEO_URL = "https://youtu.be/123456"
PAYLOAD_FREE_TEXT = "hello"


@pytest.fixture
def url_message():
    message = json.loads(BASE_PAYLOAD)
    message["incoming_text"] = PAYLOAD_VIDEO_URL
    return message


@pytest.fixture
def unknown_message():
    message = json.loads(BASE_PAYLOAD)
    message["incoming_text"]= PAYLOAD_FREE_TEXT
    return message


@pytest.fixture
def dispatcher():
    the_object = Dispatcher.__new__(Dispatcher)
    the_object.telegram = MagicMock()
    the_object.logger = MagicMock()
    the_object._send_telegram = MagicMock()
    return the_object


def test_should_dispatch_url_message(url_message, dispatcher):
    result = dispatcher.handle_event(url_message)

    assert result["status"] == STATUS_DOWNLOADER
    dispatcher._send_telegram.assert_called_once_with(
        url_message, "A video. I got this."
    )


def test_should_process_unknown_message(unknown_message, dispatcher):
    result = dispatcher.handle_event(unknown_message)

    assert result["status"] == STATUS_UNKNOWN_MESSAGE
    dispatcher._send_telegram.assert_called_once_with(
        unknown_message, "I'm not sure what to do with that."
    )
