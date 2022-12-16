import json
from unittest.mock import MagicMock

import pytest
from sauer import Dispatcher, Status

BASE_PAYLOAD = """
{
    "message": {
        "sender_name": "first_name",
        "incoming_text": "yoman",
        "chat_id": "123456789"
    }
}
"""

PAYLOAD_VIDEO_URL_1 = "https://youtu.be/123456"
PAYLOAD_VIDEO_URL_2 = "https://www.youtube.com/watch?v=0CmtDk-joT4"
PAYLOAD_VIDEO_URL_3 = "https://youtube.com/shorts/OCJMEmQPvSU?feature=share'"
PAYLOAD_FREE_TEXT = "hello"
PAYLOAD_COMMAND_1 = "/help"


@pytest.fixture
def url_message():
    payload = json.loads(BASE_PAYLOAD)
    payload["message"]["incoming_text"] = PAYLOAD_VIDEO_URL_1
    return payload


@pytest.fixture
def command_message():
    payload = json.loads(BASE_PAYLOAD)
    payload["message"]["incoming_text"] = PAYLOAD_COMMAND_1
    return payload


@pytest.fixture
def unknown_message():
    message = json.loads(BASE_PAYLOAD)
    message["incoming_text"] = PAYLOAD_FREE_TEXT
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

    assert result["status"] == Status.DOWNLOADER.name


def test_should_dispatch_command_message(command_message, dispatcher):
    result = dispatcher.handle_event(command_message)

    assert result["status"] == Status.COMMANDER.name


def test_should_process_unknown_message(unknown_message, dispatcher):
    result = dispatcher.handle_event(unknown_message)

    assert result["status"] == Status.UNKNOWN_MESSAGE.name


def test_should_recognize_different_video_urls(dispatcher):
    assert dispatcher._is_video_url(PAYLOAD_VIDEO_URL_1)
    assert dispatcher._is_video_url(PAYLOAD_VIDEO_URL_2)
    assert dispatcher._is_video_url(PAYLOAD_VIDEO_URL_3)
