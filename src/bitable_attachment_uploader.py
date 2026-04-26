from __future__ import annotations

from dataclasses import dataclass
import json
import mimetypes
from pathlib import Path
from typing import Any

try:
    from .sync_bitable import BitableSyncError, _post_multipart
except ImportError:  # pragma: no cover - supports running as a script.
    from sync_bitable import BitableSyncError, _post_multipart  # type: ignore


class BitableAttachmentUploadError(RuntimeError):
    """Raised when a bitable attachment upload cannot be completed."""


@dataclass
class BitableAttachmentUploadRequest:
    app_token: str
    attachment_paths: list[str]
    access_token: str | None = None
    endpoint: str = "https://open.feishu.cn"
    provider: str = "bitable_context_upload_user_identity"


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
    access_token: str | None = None,
    endpoint: str = "https://open.feishu.cn",
) -> BitableAttachmentUploadRequest | None:
    normalized_paths = [str(Path(path)) for path in (attachment_paths or []) if str(path).strip()]
    if not normalized_paths:
        return None
    return BitableAttachmentUploadRequest(
        app_token=app_token,
        attachment_paths=normalized_paths,
        access_token=access_token,
        endpoint=endpoint,
    )


def perform_bitable_attachment_upload(
    request: BitableAttachmentUploadRequest,
) -> BitableAttachmentUploadResult:
    if not request.access_token:
        raise BitableAttachmentUploadError(
            "Missing user access token for bitable-context attachment upload."
        )

    uploaded: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    file_tokens: list[str] = []

    for raw_path in request.attachment_paths:
        path = Path(raw_path)
        if not path.exists():
            errors.append(
                {
                    "path": raw_path,
                    "code": "file_not_found",
                    "message": f"Attachment file does not exist: {raw_path}",
                }
            )
            continue
        try:
            uploaded_item = _upload_single_attachment(
                endpoint=request.endpoint,
                app_token=request.app_token,
                access_token=request.access_token,
                file_path=path,
            )
            uploaded.append(uploaded_item)
            if uploaded_item.get("file_token"):
                file_tokens.append(str(uploaded_item["file_token"]))
        except (BitableSyncError, BitableAttachmentUploadError) as exc:
            errors.append(
                {
                    "path": str(path),
                    "file_name": path.name,
                    "code": "upload_failed",
                    "message": str(exc),
                }
            )

    ok = not errors and bool(uploaded)
    return BitableAttachmentUploadResult(
        ok=ok,
        status="completed" if ok else "partial_failed",
        provider=request.provider,
        file_tokens=file_tokens,
        uploaded=uploaded,
        errors=errors,
        message=(
            "Uploaded attachments to bitable context with user identity."
            if ok
            else "One or more attachments failed during bitable-context upload."
        ),
    )


def build_attachment_field_value(file_tokens: list[str]) -> list[dict[str, str]]:
    return [{"file_token": token} for token in file_tokens if str(token).strip()]


def load_user_access_token(token_file: str | Path) -> str:
    payload = json.loads(Path(token_file).read_text(encoding="utf-8") or "{}")
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise BitableAttachmentUploadError(f"No access_token found in token file: {token_file}")
    return token


def choose_parent_type(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    return "bitable_image" if suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"} else "bitable_file"


def _upload_single_attachment(*, endpoint: str, app_token: str, access_token: str, file_path: Path) -> dict[str, Any]:
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    parent_type = choose_parent_type(file_path)
    response = _post_multipart(
        f"{endpoint.rstrip('/')}/open-apis/drive/v1/medias/upload_all",
        fields={
            "file_name": file_path.name,
            "parent_type": parent_type,
            "parent_node": app_token,
            "size": str(file_path.stat().st_size),
        },
        file_field_name="file",
        file_name=file_path.name,
        file_bytes=file_path.read_bytes(),
        content_type=mime_type,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    data = response.get("data", {}) if isinstance(response, dict) else {}
    file_token = str(data.get("file_token") or "")
    if not file_token:
        raise BitableAttachmentUploadError(f"Feishu did not return file_token for {file_path.name}.")
    return {
        "path": str(file_path),
        "file_name": file_path.name,
        "file_token": file_token,
        "parent_type": parent_type,
        "mime_type": mime_type,
        "size": file_path.stat().st_size,
    }
