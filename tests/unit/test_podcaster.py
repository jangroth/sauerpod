import json
from unittest.mock import MagicMock

import pytest
from sauer import Status, Podcaster

SOME_METADATA = "some metadata"
SOME_RSS = "some rss"
BASE_PAYLOAD = """
{
    "message": {
        "sender_name": "first_name",
        "incoming_text": "https://youtu.be/123456",
        "chat_id": "123456"
    }
}
"""


@pytest.fixture
def base_message():
    message = json.loads(BASE_PAYLOAD)
    return message


@pytest.fixture
def podcaster():
    the_object = Podcaster.__new__(Podcaster)
    the_object.telegram = MagicMock()
    the_object.logger = MagicMock()
    the_object.storage_bucket = MagicMock()
    the_object.storage_table = MagicMock()
    the_object.jinja_env = MagicMock()
    the_object.base_url = "feed.url"
    return the_object


def test_should_generate_feed(base_message, podcaster):
    podcaster._retrieve_metadata = MagicMock(return_value=SOME_METADATA)
    podcaster._generate_rss_feed = MagicMock(return_value=SOME_RSS)
    podcaster._upload_to_s3 = MagicMock()

    result = podcaster.handle_event(base_message)

    assert result["status"] == Status.SUCCESS.name
    podcaster._retrieve_metadata.assert_called_once()
    podcaster._generate_rss_feed.assert_called_once_with(SOME_METADATA, "123456.rss")
    podcaster._upload_to_s3.assert_called_once_with("123456.rss", SOME_RSS)
