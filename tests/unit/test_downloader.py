import json
from unittest.mock import MagicMock

import pytest
from downloader.downloader import Downloader
from commonlayer.common import (
    Status,
    UploadInformation,
    VideoInformation,
)

BASE_PAYLOAD = """
{
    "message": {
        "sender_name": "first_name",
        "incoming_text": "https://youtu.be/123456",
        "chat_id": "123456"
    }
}
"""
ANY_CHAT_ID = "123123123"


@pytest.fixture
def base_message():
    message = json.loads(BASE_PAYLOAD)
    return message


@pytest.fixture
def video_information():
    return VideoInformation(
        video_id="video_id",
        title="title",
        author="author",
        description="description",
        thumbnail_url="thumbnail_url",
        duration_in_seconds=123,
        keywords="keywords",
        source_url="source_url",
    )


@pytest.fixture
def upload_information():
    return UploadInformation(
        path_to_episode="path_to_episode",
        path_to_thumbnail="path_to_thumbnail",
        timestamp_utc="timestamp_utc",
        timestamp_rfc822="timestamp_rfc822",
        episode_size="episode_size",
    )


@pytest.fixture
def downloader():
    the_object = Downloader.__new__(Downloader)
    the_object.telegram = MagicMock()
    the_object.logger = MagicMock()
    return the_object


def test_should_process_video_if_new(base_message, video_information, downloader):
    downloader._is_existing_video = MagicMock(return_value=False)
    downloader._populate_video_information = MagicMock(return_value=video_information)
    downloader._download_audio_stream = MagicMock()
    downloader._download_thumbnail = MagicMock()
    downloader._upload_to_s3 = MagicMock()
    downloader._store_metadata = MagicMock()

    result = downloader.handle_event(base_message)

    assert result["status"] == Status.PODCASTER.name
    downloader._download_audio_stream.assert_called_once()
    downloader._download_thumbnail.assert_called_once()
    downloader._upload_to_s3.assert_called_once()
    downloader._store_metadata.assert_called_once()


def test_should_ignore_video_if_not_new(base_message, downloader):
    downloader._is_existing_video = MagicMock(return_value=True)
    downloader._populate_video_information = MagicMock()
    downloader._download_to_tmp = MagicMock()
    downloader._upload_to_s3 = MagicMock()
    downloader._store_metadata = MagicMock()

    result = downloader.handle_event(base_message)

    assert result["status"] == Status.FINISH.name
    downloader._download_to_tmp.assert_not_called()
    downloader._upload_to_s3.assert_not_called()
    downloader._store_metadata.assert_not_called()


def test_should_cleanse_metadata(downloader, video_information, upload_information):
    video_information = video_information._replace(keywords="x" * 300)

    metadata = downloader._create_cleansed_metadata(
        ANY_CHAT_ID, upload_information, video_information
    )

    assert len(metadata["Keywords"]) == 250
