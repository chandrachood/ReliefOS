from __future__ import annotations

import base64
import json
import logging
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.models import CaseRecord, MediaUploadRequest, MediaUploadResponse
from app.settings import Settings

logger = logging.getLogger(__name__)


class QueuePublisher(Protocol):
    def publish_case(self, case_id: str) -> bool: ...


class NoopQueuePublisher:
    def publish_case(self, case_id: str) -> bool:
        logger.info("queue_not_configured", extra={"case_id": case_id})
        return False


class SqsQueuePublisher:
    def __init__(self, settings: Settings) -> None:
        import boto3

        if not settings.case_queue_url:
            raise ValueError("CASE_QUEUE_URL is required")
        self.queue_url = settings.case_queue_url
        self.client = boto3.client("sqs", region_name=settings.aws_region)

    def publish_case(self, case_id: str) -> bool:
        self.client.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps({"event_type": "case.created", "case_id": case_id}),
        )
        return True


def build_queue_publisher(settings: Settings) -> QueuePublisher:
    if settings.case_queue_url:
        return SqsQueuePublisher(settings)
    return NoopQueuePublisher()


@dataclass(frozen=True)
class LocalUploadTicket:
    case_id: str
    media_id: str
    token: str
    content_type: str
    size_bytes: int
    path: Path
    expires_at: float


class MediaService:
    """Creates S3 presigned uploads or bounded development-only local uploads."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._tickets: dict[tuple[str, str], LocalUploadTicket] = {}
        self._s3 = None
        if settings.media_bucket:
            import boto3

            self._s3 = boto3.client("s3", region_name=settings.aws_region)

    def create_upload(self, case: CaseRecord, request: MediaUploadRequest) -> MediaUploadResponse:
        if request.size_bytes > self.settings.max_media_bytes:
            raise ValueError(f"media exceeds {self.settings.max_media_bytes} byte limit")
        media_id = f"media_{secrets.token_hex(12)}"
        safe_suffix = Path(request.file_name).suffix.lower()[:12]
        object_key = f"cases/{case.case_id}/{media_id}{safe_suffix}"
        headers = {"Content-Type": request.content_type}

        if self._s3 and self.settings.media_bucket:
            fields = {
                "Content-Type": request.content_type,
                "x-amz-meta-case-id": case.case_id,
                "x-amz-meta-media-id": media_id,
            }
            conditions: list[object] = [
                {"Content-Type": request.content_type},
                {"x-amz-meta-case-id": case.case_id},
                {"x-amz-meta-media-id": media_id},
                ["content-length-range", 1, self.settings.max_media_bytes],
            ]
            if request.checksum_sha256:
                checksum = base64.b64encode(bytes.fromhex(request.checksum_sha256)).decode()
                fields["x-amz-checksum-sha256"] = checksum
                conditions.append({"x-amz-checksum-sha256": checksum})
            post = self._s3.generate_presigned_post(
                Bucket=self.settings.media_bucket,
                Key=object_key,
                Fields=fields,
                Conditions=conditions,
                ExpiresIn=900,
            )
            return MediaUploadResponse(
                media_id=media_id,
                upload_url=post["url"],
                method="POST",
                headers={},
                form_fields=post["fields"],
                expires_in_seconds=900,
            )

        token = secrets.token_urlsafe(32)
        path = self.settings.local_media_path / case.case_id / f"{media_id}{safe_suffix}"
        self._tickets[(case.case_id, media_id)] = LocalUploadTicket(
            case_id=case.case_id,
            media_id=media_id,
            token=token,
            content_type=request.content_type,
            size_bytes=request.size_bytes,
            path=path,
            expires_at=time.monotonic() + 900,
        )
        return MediaUploadResponse(
            media_id=media_id,
            upload_url=f"/v1/local-media/{case.case_id}/{media_id}",
            headers={**headers, "X-Upload-Token": token},
            expires_in_seconds=900,
        )

    def consume_local_ticket(
        self, case_id: str, media_id: str, token: str, content_type: str, body: bytes
    ) -> Path:
        ticket = self._tickets.pop((case_id, media_id), None)
        if (
            not ticket
            or time.monotonic() > ticket.expires_at
            or not secrets.compare_digest(ticket.token, token)
        ):
            raise PermissionError("invalid or expired upload ticket")
        if content_type != ticket.content_type:
            raise ValueError("content type does not match upload ticket")
        if len(body) != ticket.size_bytes or len(body) > self.settings.max_media_bytes:
            raise ValueError("content length does not match upload ticket")
        ticket.path.parent.mkdir(parents=True, exist_ok=True)
        ticket.path.write_bytes(body)
        return ticket.path
