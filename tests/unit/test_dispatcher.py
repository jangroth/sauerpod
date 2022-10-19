import json
from unittest.mock import MagicMock

import pytest
from sauer import STATUS_DOWNLOADER, STATUS_UNKNOWN_MESSAGE, Dispatcher

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

MESSAGE_VIDEO_URL = "https://youtu.be/123456"
MESSAGE_FREE_TEXT = "hello"


@pytest.fixture
def url_message():
    message = json.loads(BASE_MESSAGE)
    message["message"]["text"] = MESSAGE_VIDEO_URL
    return message


@pytest.fixture
def unknown_message():
    message = json.loads(BASE_MESSAGE)
    message["message"]["text"] = MESSAGE_FREE_TEXT
    return message


@pytest.fixture
def dispatcher():
    the_object = Dispatcher.__new__(Dispatcher)
    the_object.telegram = MagicMock()
    the_object.logger = MagicMock()
    return the_object


def test_should_dispatch_url_message(url_message, dispatcher):
    result = dispatcher.handle_event(url_message)
    assert result["status"] == STATUS_DOWNLOADER


def test_should_process_unknown_message(unknown_message, dispatcher):
    result = dispatcher.handle_event(unknown_message)
    assert result["status"] == STATUS_UNKNOWN_MESSAGE
