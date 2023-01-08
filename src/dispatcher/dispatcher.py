import logging
import os
from common import Payload, Status, TelegramNotifier, notify_cloudwatch


class Dispatcher:
    """Parses incomming message and returns result for dispatching."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(os.environ.get("LOGGING", logging.DEBUG))
        self.telegram = TelegramNotifier()

    def _send_telegram(self, sender_name, incoming_text, response_text):
        self.telegram.send(
            text=f"Hello {sender_name}, you said '{incoming_text}'.\n\n{response_text}",
        )

    def _is_video_url(self, text):
        return (
            text.startswith("https://youtu.be")
            or text.startswith("https://www.youtube.com")
            or text.startswith("https://youtube.com")
        )

    def _is_command(self, text):
        return text.startswith("/")

    def handle_event(self, event):
        try:
            self.logger.info(f"{self.__class__.__name__} - called with {event}")
            payload = Payload(**event["message"])
            if self._is_video_url(payload.incoming_text):
                status = Status.DOWNLOADER
            elif self._is_command(payload.incoming_text):
                status = Status.COMMANDER
            else:
                self.telegram.send(
                    text=f"Hello {payload.sender_name}, you said '{payload.incoming_text}'.\n\nI don't know what to do with that.",
                )
                status = Status.FINISH
        except Exception as e:
            self.logger.exception(e)
            self.telegram.send(f"⚠️ Error:\n{e}")
            status = Status.FAILURE
        return dict(status=status.name, message=event["message"])


@notify_cloudwatch
def dispatcher_handler(event, context) -> dict:
    return Dispatcher().handle_event(event)
