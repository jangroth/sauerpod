import boto3
import email
import logging
import os
from boto3.dynamodb.conditions import Attr, Key
from common import (
    notify_cloudwatch,
    Payload,
    Status,
    TelegramNotifier,
    UploadInformation,
    VideoInformation,
)
from datetime import datetime
from pathlib import Path
from pytube import YouTube
from urllib import request


class Downloader:
    """Downloads video from submitted URL, stores in S3 & DynamoDB"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.telegram = TelegramNotifier()
        self.storage_bucket_name = os.environ["STORAGE_BUCKET_NAME"]
        self.storage_bucket = boto3.resource("s3").Bucket(self.storage_bucket_name)
        self.storage_table_name = os.environ["STORAGE_TABLE_NAME"]
        self.storage_table = boto3.resource("dynamodb").Table(self.storage_table_name)

    def _populate_video_information(self, url: str):
        self.logger.info(f"Downloading video from {url}")
        yt = YouTube(url)
        return VideoInformation(
            video_id=yt.video_id,
            title=yt.title,
            author=yt.author,
            description=yt.description,
            thumbnail_url=yt.thumbnail_url,
            duration_in_seconds=yt.length,
            keywords=yt.keywords,
            source_url=url,
        )

    def _is_existing_video(self, video_information: VideoInformation, chat_id: str):
        self.logger.info(f"Is this new? {video_information}")
        return self.storage_table.query(
            KeyConditionExpression=Key("FeedId").eq(chat_id),
            FilterExpression=Attr("EpisodeId").eq(video_information.video_id),
        )["Items"]

    def _download_audio_stream(self, video_information: VideoInformation) -> str:
        return (
            YouTube(video_information.source_url)
            .streams.filter(only_audio=True)
            .filter(subtype="mp4")
            .order_by("abr")
            .desc()
            .first()
            .download(output_path="/tmp", filename=f"{video_information.video_id}.mp4")
        )

    def _download_thumbnail(self, video_information: VideoInformation) -> str:
        url_without_query_string = video_information.thumbnail_url.split("?")[0]
        _, file_extension = os.path.splitext(url_without_query_string)
        return request.urlretrieve(
            url=video_information.thumbnail_url,
            filename=f"/tmp/{video_information.video_id}_logo{file_extension}",
        )[0]

    def _upload_to_s3(
        self, chat_id: str, audio_file_path: str, thumbnail_file_path: str
    ):
        audio_bucket_path = f"audio/{chat_id}/{os.path.basename(audio_file_path)}"
        audio_file_size = Path(audio_file_path).stat().st_size
        self.storage_bucket.upload_file(audio_file_path, audio_bucket_path)

        thumbnail_bucket_path = (
            f"audio/{chat_id}/{os.path.basename(thumbnail_file_path)}"
        )
        self.storage_bucket.upload_file(thumbnail_file_path, thumbnail_bucket_path)

        now = datetime.utcnow()
        return UploadInformation(
            path_to_episode=audio_bucket_path,
            path_to_thumbnail=thumbnail_bucket_path,
            timestamp_utc=int(now.timestamp()),
            timestamp_rfc822=email.utils.format_datetime(now),
            episode_size=audio_file_size,
        )

    def _create_cleansed_metadata(
        self,
        chat_id: str,
        upload_information: UploadInformation,
        video_information: VideoInformation,
    ) -> dict:
        return dict(
            [
                ("FeedId", chat_id),
                ("EpisodeId", video_information.video_id),
                ("Title", video_information.title),
                ("Author", video_information.author),
                ("Description", video_information.description),
                ("DurationInSeconds", video_information.duration_in_seconds),
                ("Keywords", video_information.keywords[:250]),
                ("FileLengthInByte", upload_information.episode_size),
                ("BucketPathEpisode", upload_information.path_to_episode),
                ("BucketPathThumbnail", upload_information.path_to_thumbnail),
                ("TimestampUtc", str(upload_information.timestamp_utc)),
                ("TimestampRfc822", upload_information.timestamp_rfc822),
            ]
        )

    def _store_metadata(self, metadata: dict):
        self.storage_table.put_item(Item=metadata)
        self.logger.info(f"Storing metadata: {metadata}")

    def handle_event(self, event):
        try:
            self.logger.info(f"{self.__class__.__name__} - called with {event}")
            payload = Payload(**event["message"])
            video_information = self._populate_video_information(payload.incoming_text)
            if not self._is_existing_video(video_information, payload.chat_id):
                self.telegram.send("...Downloading video.")
                audio_file_path = self._download_audio_stream(video_information)
                thumbnail_file_path = self._download_thumbnail(video_information)
                upload_information = self._upload_to_s3(
                    chat_id=payload.chat_id,
                    audio_file_path=audio_file_path,
                    thumbnail_file_path=thumbnail_file_path,
                )
                metadata = self._create_cleansed_metadata(
                    video_information=video_information,
                    chat_id=payload.chat_id,
                    upload_information=upload_information,
                )
                self._store_metadata(metadata)
                status = Status.PODCASTER
            else:
                self.telegram.send(
                    f"...'{video_information.title}' is already in your cast. Skipping download.",
                )
                status = Status.FINISH
        except Exception as e:
            self.logger.exception(e)
            self.telegram.send(f"⚠️ Error:\n{e}")
            status = Status.FAILURE
        return dict(status=status.name, message=event["message"])


@notify_cloudwatch
def downloader_handler(event, context) -> dict:
    return Downloader().handle_event(event)
