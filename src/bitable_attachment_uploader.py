from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class BitableAttachmentUploadError(RuntimeError):
    """Raised when a bitable attachment upload cannot be completed."""


@dataclass
class BitableAttachmentUploadRequest:
    app_token: str
    attachment_paths: list[str]
    provider: str = "bitable_context_upload"
    parent_type: str = "bitable_image"


@dataclass
class BitableAttachmentUploadResult:
    ok: bool
    status: str
    provider: str
    file_tokens: list[str]
    uploaded: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    message: str


def build_bitable_attachment_upload_request(
    *,
    app_token: str,
    attachment_paths: list[str] | None,
) -> BitableAttachmentUploadRequest | None:
    normalized_paths = [str(Path(path)) for path in (attachment_paths or []) if str(path).strip()]
    if not normalized_paths:
        return None
    return BitableAttachmentUploadRequest(
        app_token=app_token,
        attachment_paths=normalized_paths,
    )


def perform_bitable_attachment_upload(
    request: BitableAttachmentUploadRequest,
) -> BitableAttachmentUploadResult:
    """Structured placeholder until the runtime exposes a bitable-context upload primitive."""
    uploaded: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for path in request.attachment_paths:
        name = Path(path).name
        errors.append(
            {
                "path": path,
                "file_name": name,
                "code": "bitable_context_upload_unavailable",
                "message": (
                    "The current runtime does not expose a bitable-context media upload primitive. "
                    "Do not fall back to generic Drive upload tokens for bitable attachment fields."
                ),
            }
        )

    return BitableAttachmentUploadResult(
        ok=False,
        status="not_supported_yet",
        provider=request.provider,
        file_tokens=[],
        uploaded=uploaded,
        errors=errors,
        message=(
            "Bitable attachment upload requires a bitable-context media upload capability that is "
            "not available in the current runtime."
        ),
    )


def build_attachment_field_value(file_tokens: list[str]) -> list[dict[str, str]]:
    return [{"file_token": token} for token in file_tokens if str(token).strip()]
