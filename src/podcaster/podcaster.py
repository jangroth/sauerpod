import boto3
import email
import logging
import os
import tempfile
from boto3.dynamodb.conditions import Key
from common import Payload, TelegramNotifier, notify_cloudwatch, Status
from datetime import datetime
from jinja2 import Environment, select_autoescape, FileSystemLoader


class Podcaster:
    """Generates podcast feed and uploads to S3"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.telegram = TelegramNotifier()
        self.storage_bucket_name = os.environ["STORAGE_BUCKET_NAME"]
        self.storage_bucket = boto3.resource("s3").Bucket(self.storage_bucket_name)
        self.storage_table_name = os.environ["STORAGE_TABLE_NAME"]
        self.storage_table = boto3.resource("dynamodb").Table(self.storage_table_name)
        self.base_url = f'https://{os.environ["DISTRIBUTION_DOMAIN_NAME"]}'
        self.jinja_env = Environment(
            loader=FileSystemLoader("templates"),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def _retrieve_metadata(self, chat_id):
        return self.storage_table.query(
            KeyConditionExpression=Key("FeedId").eq(chat_id), ScanIndexForward=False
        )["Items"]

    def _generate_rss_feed(self, metadata, feed_name):
        template = self.jinja_env.get_template("podcast.xml.j2")
        output = template.render(
            dict(
                podcast=dict(
                    last_build_date=email.utils.format_datetime(datetime.now()),
                    base_url=self.base_url,
                    feed_url=f"{self.base_url}/{feed_name}",
                    title="Sauerpod Cast",
                    episodes=metadata,
                )
            )
        )
        return output

    def _upload_to_s3(self, feed_name: str, feed_content: str):
        with tempfile.NamedTemporaryFile(mode="w") as tmp_file:
            tmp_file.write(feed_content)
            tmp_file.flush()
            self.storage_bucket.upload_file(
                Filename=tmp_file.name,
                Key=feed_name,
                ExtraArgs={"ContentType": "application/rss+xml"},
            )

    def handle_event(self, event):
        try:
            self.logger.info(f"{self.__class__.__name__} - called with {event}")
            payload = Payload(**event["message"])
            metadata = self._retrieve_metadata(payload.chat_id)
            feed_name = f"{payload.chat_id}.rss"
            feed_url = f"{self.base_url}/{feed_name}"
            feed_content = self._generate_rss_feed(metadata, feed_name)
            self._upload_to_s3(feed_name, feed_content)
            self.telegram.send(
                f"""...Podcast feed generated and uploaded:
                \n <a href="{feed_url}">🎧 {feed_url} 🎧</a>
                """,
            )
            status = Status.FINISH
        except Exception as e:
            self.logger.exception(e)
            self.telegram.send(f"⚠️ Error:\n{e}")
            status = Status.FAILURE
        return dict(status=status.name, message=event["message"])


@notify_cloudwatch
def podcaster_handler(event, context) -> dict:
    return Podcaster().handle_event(event)
