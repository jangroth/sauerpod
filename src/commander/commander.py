import boto3
import logging
import os
import textwrap
import time
from boto3.dynamodb.conditions import Attr, Key
from common import TelegramNotifier, Payload, Status, notify_cloudwatch
from datetime import timedelta


class Commander:
    """Process commands"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.telegram = TelegramNotifier()
        self.storage_bucket_name = os.environ["STORAGE_BUCKET_NAME"]
        self.storage_bucket = boto3.resource("s3").Bucket(self.storage_bucket_name)
        self.storage_table_name = os.environ["STORAGE_TABLE_NAME"]
        self.storage_table = boto3.resource("dynamodb").Table(self.storage_table_name)
        self.base_url = f'https://{os.environ["DISTRIBUTION_DOMAIN_NAME"]}'

    def _convert_to_line_item(self, episode: dict, now: float, compact: bool) -> str:
        title = (
            (episode["Title"][:25] + "..")
            if len(episode["Title"]) > 27 and compact
            else episode["Title"]
        )
        age = timedelta(seconds=int(now - int(episode["TimestampUtc"])))
        episode_link = f"<a href='{self.base_url}/{episode['BucketPathEpisode']}'>{episode['EpisodeId']}</a>"
        return f"* <i>{title}</i> ({episode_link}, <b>-{age}</b>) "

    def _query_episodes(self, feed_id: str, ascending: bool, limit: int = None) -> dict:
        kwargs = {
            "KeyConditionExpression": Key("FeedId").eq(feed_id),
            "ScanIndexForward": ascending,
        }
        if limit:
            kwargs["Limit"] = limit
        return self.storage_table.query(**kwargs)["Items"]

    def _delete_episode(self, chat_id, episode_id) -> str:
        try:
            episode = next(
                episode
                for episode in self.storage_table.query(
                    KeyConditionExpression=Key("FeedId").eq(chat_id),
                    FilterExpression=Key("EpisodeId").eq(episode_id),
                )["Items"]
            )
            self.storage_bucket.delete_objects(
                Delete={"Objects": [{"Key": episode["BucketPathThumbnail"]}]}
            )
            self.storage_bucket.delete_objects(
                Delete={"Objects": [{"Key": episode["BucketPathEpisode"]}]}
            )
            self.storage_table.delete_item(
                Key={"FeedId": chat_id, "TimestampUtc": episode["TimestampUtc"]},
                ConditionExpression=Attr("EpisodeId").eq(episode_id),
            )
            result = f"Episode {episode_id} deleted."
        except StopIteration:
            result = f"Couldn't find episode <pre>{episode_id}</pre> in database. Is this the right id?"
        return result

    def _cmd_list(self, command, chat_id) -> None:
        now = time.time()
        result = [
            self._convert_to_line_item(episode, now, not command.endswith("full"))
            for episode in self._query_episodes(feed_id=chat_id, ascending=False)
        ]
        self.telegram.send("\n".join(result))

    def _cmd_delete(self, command, chat_id) -> bool:
        try:
            command_fragments = command.split()
            command_text = command_fragments[0]
            if command_text == "/deletenewest":
                episode_id = self._query_episodes(feed_id=chat_id, ascending=False)[0][
                    "EpisodeId"
                ]
            elif command_text == "/deleteoldest":
                episode_id = self._query_episodes(feed_id=chat_id, ascending=True)[0][
                    "EpisodeId"
                ]
            elif len(command_fragments) == 2:
                episode_id = command_fragments[1]
            else:
                raise ValueError()
            message = self._delete_episode(chat_id=chat_id, episode_id=episode_id)
            update_required = True
        except ValueError:
            message = f"I don't understand '{command}'."
            update_required = False
        self.telegram.send(message)
        return update_required

    def _cmd_help(self):
        self.telegram.send(
            textwrap.dedent(
                f"""\
                I understand these commands:
                <pre> {'/help':<20}</pre>This text.
                <pre> {'/list':<20}</pre>List entries in database (compact layout).
                <pre> {'/listfull':<20}</pre>List entries in database (full layout).
                <pre> {'/delete [id]':<20}</pre>Delete entry from database.
                <pre> {'/deletenewest':<20}</pre>Delete newest entry from database.
                <pre> {'/deleteoldest':<20}</pre>Delete oldest entry from database.
                """
            ),
        )

    def handle_event(self, event: dict):
        try:
            self.logger.info(f"{self.__class__.__name__} - called with {event}")
            payload = Payload(**event["message"])
            command = payload.incoming_text
            if command.startswith("/list"):
                self._cmd_list(command=command, chat_id=payload.chat_id)
                status = Status.FINISH
            if command.startswith("/delete"):
                update_required = self._cmd_delete(
                    command=command, chat_id=payload.chat_id
                )
                status = Status.PODCASTER if update_required else Status.FINISH
            elif command.startswith("/help"):
                self._cmd_help()
                status = Status.FINISH
        except Exception as e:
            self.logger.exception(e)
            self.telegram.send(f"⚠️ Error:\n{e}")
            status = Status.FAILURE
        return dict(status=status.name, message=event["message"])


@notify_cloudwatch
def commander_handler(event, context) -> dict:
    return Commander().handle_event(event)


if __name__ == "__main__":
    stack_outputs = boto3.client("cloudformation").describe_stacks(
        StackName="sauerpod-storage-stack"
    )["Stacks"][0]["Outputs"]
    bucket_name = next(
        output["OutputValue"]
        for output in stack_outputs
        if output["OutputKey"] == "StorageBucketNameCfn"
    )
    table_name = next(
        output["OutputValue"]
        for output in stack_outputs
        if output["OutputKey"] == "StorageTableNameCfn"
    )
    stack_outputs = boto3.client("cloudformation").describe_stacks(
        StackName="sauerpod-publish-stack"
    )["Stacks"][0]["Outputs"]
    domain_name = next(
        output["OutputValue"]
        for output in stack_outputs
        if output["OutputKey"] == "DistributionDomainNameCfn"
    )
    os.environ["STORAGE_TABLE_NAME"] = table_name
    os.environ["STORAGE_BUCKET_NAME"] = bucket_name
    os.environ["DISTRIBUTION_DOMAIN_NAME"] = domain_name
    event = dict(
        message=dict(
            sender_name="foo",
            incoming_text="/deletefirst",
            chat_id="173229021",
        )
    )
    payload = Payload(**event["message"])
    Commander().handle_event(event)
