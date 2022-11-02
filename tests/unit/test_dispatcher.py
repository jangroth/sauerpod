import json
from unittest.mock import MagicMock

import pytest
from sauer import STATUS_DOWNLOADER, STATUS_UNKNOWN_MESSAGE, Dispatcher

BASE_PAYLOAD = """
{
    "message": {
        "incoming_text": "yoman",
        "sender": "first_name"
    }
}
"""

PAYLOAD_VIDEO_URL_1 = "https://youtu.be/123456"
PAYLOAD_VIDEO_URL_2 = "https://www.youtube.com/watch?v=0CmtDk-joT4"
PAYLOAD_FREE_TEXT = "hello"


@pytest.fixture
def url_message():
    payload = json.loads(BASE_PAYLOAD)
    payload["message"]["incoming_text"] = PAYLOAD_VIDEO_URL_1
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

    assert result["status"] == STATUS_DOWNLOADER
    dispatcher._send_telegram.assert_called_once_with(
        url_message["message"], "...A video. I got this."
    )


def test_should_process_unknown_message(unknown_message, dispatcher):
    result = dispatcher.handle_event(unknown_message)

    assert result["status"] == STATUS_UNKNOWN_MESSAGE
    dispatcher._send_telegram.assert_called_once_with(
        unknown_message["message"], "...I'm not sure what to do with that."
    )


def test_should_recognize_different_video_urls(dispatcher):
    assert dispatcher._is_video_url(PAYLOAD_VIDEO_URL_1)
    assert dispatcher._is_video_url(PAYLOAD_VIDEO_URL_2)
