import json
from unittest.mock import MagicMock

import pytest
from sauer import STATUS_NO_ACTION, STATUS_SUCCESS, Downloader

BASE_PAYLOAD = """
{
    "incoming_text": "https://youtu.be/123456",
    "sender": "first_name"
}
"""


@pytest.fixture
def base_message():
    message = json.loads(BASE_PAYLOAD)
    return message


@pytest.fixture
def downloader():
    the_object = Downloader.__new__(Downloader)
    the_object.telegram = MagicMock()
    the_object.logger = MagicMock()
    the_object._send_telegram = MagicMock()
    return the_object


def test_should_process_video_if_new(base_message, downloader):
    downloader._is_new_video = MagicMock(return_value=True)
    downloader._populate_video_information = MagicMock()
    downloader._download_to_tmp = MagicMock()
    downloader._upload_to_s3 = MagicMock()
    downloader._store_metadata = MagicMock()

    result = downloader.handle_event(base_message)

    assert result["status"] == STATUS_SUCCESS
    downloader._download_to_tmp.assert_called_once()
    downloader._upload_to_s3.assert_called_once()
    downloader._store_metadata.assert_called_once()


def test_should_ignore_video_if_not_new(base_message, downloader):
    downloader._is_new_video = MagicMock(return_value=False)
    downloader._populate_video_information = MagicMock()
    downloader._download_to_tmp = MagicMock()
    downloader._upload_to_s3 = MagicMock()
    downloader._store_metadata = MagicMock()

    result = downloader.handle_event(base_message)

    assert result["status"] == STATUS_NO_ACTION
    downloader._download_to_tmp.assert_not_called()
    downloader._upload_to_s3.assert_not_called()
    downloader._store_metadata.assert_not_called()
