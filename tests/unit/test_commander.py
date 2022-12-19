import json
from unittest.mock import MagicMock

import pytest

from sauer import (
    Status,
    Commander,
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
HELP_COMMAND = "/help"
LIST_COMMAND = "/list"
LISTFULL_COMMAND = "/listfull"
DELETE_COMMAND = "/delete id123"
DELETENEWEST_COMMAND = "/deletenewest"
DELETEOLDEST_COMMAND = "/deleteoldest"
METADATA = [
    dict(
        Title="123456789012345678901234567890",
        TimestampUtc=1644796800,  # 02/14/2022, 12:00:00 am
        BucketPathEpisode="foo/bar/baz",
        EpisodeId="id123",
    ),
    dict(
        Title="abcdefghijklmnopqrstuvwxyz",
        TimestampUtc=1644883200,  # 02/15/2022, 12:00:00 am
        BucketPathEpisode="baz/foo/bar",
        EpisodeId="idabc",
    ),
]


@pytest.fixture
def help_command():
    payload = json.loads(BASE_PAYLOAD)
    payload["message"]["incoming_text"] = HELP_COMMAND
    return payload


@pytest.fixture
def list_command():
    payload = json.loads(BASE_PAYLOAD)
    payload["message"]["incoming_text"] = LIST_COMMAND
    return payload


@pytest.fixture
def listfull_command():
    payload = json.loads(BASE_PAYLOAD)
    payload["message"]["incoming_text"] = LISTFULL_COMMAND
    return payload


@pytest.fixture
def delete_command():
    payload = json.loads(BASE_PAYLOAD)
    payload["message"]["incoming_text"] = DELETE_COMMAND
    return payload


@pytest.fixture
def deletefirst_command():
    payload = json.loads(BASE_PAYLOAD)
    payload["message"]["incoming_text"] = DELETENEWEST_COMMAND
    return payload


@pytest.fixture
def deletelast_command():
    payload = json.loads(BASE_PAYLOAD)
    payload["message"]["incoming_text"] = DELETEOLDEST_COMMAND
    return payload


@pytest.fixture
def commander():
    the_object = Commander.__new__(Commander)
    the_object.telegram = MagicMock()
    the_object.logger = MagicMock()
    the_object.base_url = "base_url"
    return the_object


def test_should_process_help_command(commander, help_command):
    result = commander.handle_event(help_command)

    assert result["status"] == Status.FINISH.name
    commander.telegram.send.assert_called_once()


def test_should_process_list_command(commander, list_command, freezer):
    freezer.move_to("2022-02-16")
    commander._query_episodes = MagicMock(return_value=METADATA)

    result = commander.handle_event(list_command)

    assert result["status"] == Status.FINISH.name
    name, args, _ = commander.telegram.mock_calls[0]
    assert name == "send"
    assert "1234567890123456789012345.." in args[0]
    assert "href='base_url/foo/bar/baz'" in args[0]
    assert "id123" in args[0]
    assert "-2 days, 0:00:00" in args[0]
    assert "abcdefghijklmnopqrstuvwxyz" in args[0]
    assert "href='base_url/baz/foo/bar'" in args[0]
    assert "idabc" in args[0]
    assert "-1 day, 0:00:00" in args[0]


def test_should_process_listfull_command(commander, listfull_command, freezer):
    freezer.move_to("2022-02-16")
    commander._query_episodes = MagicMock(return_value=METADATA)

    result = commander.handle_event(listfull_command)

    assert result["status"] == Status.FINISH.name
    name, args, _ = commander.telegram.mock_calls[0]
    assert name == "send"
    assert "123456789012345678901234567890" in args[0]
    assert "href='base_url/foo/bar/baz'" in args[0]
    assert "id123" in args[0]
    assert "-2 days, 0:00:00" in args[0]
    assert "abcdefghijklmnopqrstuvwxyz" in args[0]
    assert "href='base_url/baz/foo/bar'" in args[0]
    assert "idabc" in args[0]
    assert "-1 day, 0:00:00" in args[0]


def test_should_process_correct_delete_command(commander, delete_command):
    commander._delete_episode = MagicMock()

    result = commander.handle_event(delete_command)

    assert result["status"] == Status.PODCASTER.name
    commander._delete_episode.assert_called_once_with(
        chat_id="123456", episode_id="id123"
    )


def test_should_process_incomplete_delete_command(commander, delete_command):
    delete_command["message"]["incoming_text"] = "/delete"
    commander._delete_episode = MagicMock()

    result = commander.handle_event(delete_command)

    assert result["status"] == Status.FINISH.name
    commander._delete_episode.assert_not_called()
    commander.telegram.send.assert_called_once()


def test_should_process_deletefirst_command(commander, deletefirst_command):
    commander._delete_episode = MagicMock()
    commander._query_episodes = MagicMock(return_value=METADATA[:1])

    result = commander.handle_event(deletefirst_command)

    assert result["status"] == Status.PODCASTER.name
    commander._delete_episode.assert_called_once_with(
        chat_id="123456", episode_id="id123"
    )


def test_should_process_deletelast_command(commander, deletelast_command):
    commander._delete_episode = MagicMock()
    commander._query_episodes = MagicMock(return_value=METADATA[:1])

    result = commander.handle_event(deletelast_command)

    assert result["status"] == Status.PODCASTER.name
    commander._delete_episode.assert_called_once_with(
        chat_id="123456", episode_id="id123"
    )
