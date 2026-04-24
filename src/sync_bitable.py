from __future__ import annotations

import json
import mimetypes
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error, request


TRANSPORTATION_TYPES = {"transportation_fee"}

TRANSPORT_FIELD_NAMES = {
    "doc_id": "doc_id",
    "expense_type": "报销类型",
    "source_file_name": "源文件名",
    "attachment": "票据附件",
    "invoice_number": "票据号码",
    "amount": "金额",
    "currency": "币种",
    "buyer_name": "购票主体",
    "buyer_tax_id": "购票主体税号",
    "passenger_name": "乘车人",
    "transport_number": "车次",
    "from_station": "出发站",
    "to_station": "到达站",
    "travel_date": "乘车日期",
    "departure_time": "发车时间",
    "seat_no": "座位号",
    "seat_class": "座席",
    "validation_status": "校验状态",
    "needs_review": "是否复核",
    "review_reasons": "复核原因",
    "raw_json": "原始JSON",
}

EXPENSE_FIELD_NAMES = {
    "doc_id": "doc_id",
    "expense_type": "报销类型",
    "source_file_name": "源文件名",
    "attachment": "票据附件",
    "invoice_number": "票据号码",
    "issue_date": "开票日期",
    "amount": "金额",
    "currency": "币种",
    "buyer_name": "购买方名称",
    "buyer_tax_id": "购买方税号",
    "seller_name": "销售方名称",
    "seller_tax_id": "销售方税号",
    "item_name": "项目名称",
    "quantity": "数量",
    "unit_price": "单价",
    "line_amount": "项目金额",
    "tax_rate": "税率",
    "tax_amount": "税额",
    "line_items_json": "项目明细JSON",
    "validation_status": "校验状态",
    "needs_review": "是否复核",
    "review_reasons": "复核原因",
    "raw_json": "原始JSON",
}


class BitableSyncError(RuntimeError):
    """Raised when the Feishu Bitable sync fails."""


@dataclass
class BitableSettings:
    enabled: bool
    dry_run: bool
    endpoint: str
    batch_size: int
    app_id: str
    app_secret: str
    app_token: str
    transport_table_id: str
    expense_table_id: str


def sync_skill_result_with_config(
    skill_result: dict[str, Any],
    config: dict[str, Any],
    *,
    attachment_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Sync a skill_result payload to Feishu Bitable using app config settings."""
    settings = load_bitable_settings(config)
    if not settings.enabled:
        return {
            "enabled": False,
            "status": "disabled",
            "message": "Bitable sync is disabled in configuration.",
        }

    return sync_skill_result_to_bitable(
        skill_result,
        settings,
        attachment_paths=attachment_paths,
    )


def load_bitable_settings(config: dict[str, Any]) -> BitableSettings:
    """Load Bitable settings from config with environment-variable overrides."""
    bitable = config.get("sync", {}).get("bitable", {})
    endpoint = str(bitable.get("endpoint") or "https://open.feishu.cn").rstrip("/")
    batch_size = int(bitable.get("batch_size") or 200)

    app_id = _resolve_secret(bitable, "app_id")
    app_secret = _resolve_secret(bitable, "app_secret")
    app_token = _resolve_secret(bitable, "app_token")
    transport_table_id = _resolve_secret(bitable, "transport_table_id")
    expense_table_id = _resolve_secret(bitable, "expense_table_id")

    return BitableSettings(
        enabled=bool(bitable.get("enabled", False)),
        dry_run=bool(bitable.get("dry_run", True)),
        endpoint=endpoint,
        batch_size=max(1, min(batch_size, 500)),
        app_id=app_id,
        app_secret=app_secret,
        app_token=app_token,
        transport_table_id=transport_table_id,
        expense_table_id=expense_table_id,
    )


def sync_skill_result_to_bitable(
    skill_result: dict[str, Any],
    settings: BitableSettings,
    *,
    attachment_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Write skill_result documents into transport and expense Bitable tables."""
    documents = skill_result.get("documents", [])
    if not isinstance(documents, list):
        raise BitableSyncError("skill_result.documents must be a list.")

    attachment_index = _build_attachment_index(attachment_paths or [])
    transport_records: list[dict[str, Any]] = []
    expense_records: list[dict[str, Any]] = []

    access_token = ""
    if not settings.dry_run:
        access_token = get_tenant_access_token(settings)

    for document in documents:
        if not isinstance(document, dict):
            continue

        attachment_payload = _build_attachment_field(
            document=document,
            settings=settings,
            access_token=access_token,
            attachment_index=attachment_index,
        )

        invoice_type = str(document.get("document_type") or "unknown")
        if invoice_type in TRANSPORTATION_TYPES:
            transport_records.append(build_transport_record(document, attachment_payload))
        else:
            expense_records.append(build_expense_record(document, attachment_payload))

    summary = {
        "enabled": True,
        "dry_run": settings.dry_run,
        "status": "dry_run" if settings.dry_run else "completed",
        "app_token": settings.app_token,
        "tables": {
            "transport": {
                "table_id": settings.transport_table_id,
                "records_prepared": len(transport_records),
                "records_written": 0,
            },
            "expense": {
                "table_id": settings.expense_table_id,
                "records_prepared": len(expense_records),
                "records_written": 0,
            },
        },
    }

    if settings.dry_run:
        summary["tables"]["transport"]["preview"] = transport_records[:3]
        summary["tables"]["expense"]["preview"] = expense_records[:3]
        return summary

    if transport_records:
        written = batch_create_records(
            settings=settings,
            access_token=access_token,
            table_id=settings.transport_table_id,
            records=transport_records,
        )
        summary["tables"]["transport"]["records_written"] = written

    if expense_records:
        written = batch_create_records(
            settings=settings,
            access_token=access_token,
            table_id=settings.expense_table_id,
            records=expense_records,
        )
        summary["tables"]["expense"]["records_written"] = written

    return summary


def get_tenant_access_token(settings: BitableSettings) -> str:
    """Fetch a tenant access token for the configured Feishu app."""
    if not settings.app_id or not settings.app_secret:
        raise BitableSyncError("Missing FEISHU_APP_ID or FEISHU_APP_SECRET.")

    response = _post_json(
        f"{settings.endpoint}/open-apis/auth/v3/tenant_access_token/internal",
        {
            "app_id": settings.app_id,
            "app_secret": settings.app_secret,
        },
    )
    token = str(response.get("tenant_access_token") or "")
    if not token:
        raise BitableSyncError("Failed to obtain tenant_access_token from Feishu.")
    return token


def batch_create_records(
    *,
    settings: BitableSettings,
    access_token: str,
    table_id: str,
    records: list[dict[str, Any]],
) -> int:
    """Write records to a Feishu Bitable table in batches."""
    if not table_id:
        raise BitableSyncError("Missing Bitable table_id.")

    total_written = 0
    for chunk in _chunk_records(records, settings.batch_size):
        response = _post_json(
            (
                f"{settings.endpoint}/open-apis/bitable/v1/apps/"
                f"{settings.app_token}/tables/{table_id}/records/batch_create"
            ),
            {"records": chunk},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        data = response.get("data", {})
        items = data.get("records", []) if isinstance(data, dict) else []
        total_written += len(items) if items else len(chunk)
    return total_written


def upload_attachment(
    *,
    settings: BitableSettings,
    access_token: str,
    file_path: str | Path,
) -> dict[str, Any]:
    """Upload a local receipt file to Feishu so it can be attached in Bitable."""
    path = Path(file_path)
    if not path.exists():
        raise BitableSyncError(f"Attachment file does not exist: {path}")

    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    response = _post_multipart(
        f"{settings.endpoint}/open-apis/drive/v1/medias/upload_all",
        fields={
            "file_name": path.name,
            "parent_type": "bitable_file",
            "parent_node": settings.app_token,
            "size": str(path.stat().st_size),
        },
        file_field_name="file",
        file_name=path.name,
        file_bytes=path.read_bytes(),
        content_type=mime_type,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    data = response.get("data", {})
    file_token = str(data.get("file_token") or "")
    if not file_token:
        raise BitableSyncError(f"Feishu did not return file_token for {path.name}.")
    return {
        "file_token": file_token,
        "name": path.name,
        "type": mime_type,
        "size": path.stat().st_size,
    }


def build_transport_record(
    document: dict[str, Any],
    attachment_payload: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Map a skill document into the transport reimbursement table schema."""
    extraction = _ensure_dict(document.get("extraction"))
    doc = _ensure_dict(extraction.get("document"))
    buyer = _ensure_dict(extraction.get("buyer"))
    travel = _ensure_dict(extraction.get("travel"))
    passenger = _ensure_dict(extraction.get("passenger"))
    validation = _ensure_dict(document.get("validation"))
    review = _ensure_dict(document.get("review"))

    fields = {
        TRANSPORT_FIELD_NAMES["doc_id"]: document.get("doc_id"),
        TRANSPORT_FIELD_NAMES["expense_type"]: _map_expense_type(document.get("document_type")),
        TRANSPORT_FIELD_NAMES["source_file_name"]: document.get("source_file_name"),
        TRANSPORT_FIELD_NAMES["attachment"]: attachment_payload or [],
        TRANSPORT_FIELD_NAMES["invoice_number"]: doc.get("invoice_number"),
        TRANSPORT_FIELD_NAMES["amount"]: doc.get("amount"),
        TRANSPORT_FIELD_NAMES["currency"]: doc.get("currency"),
        TRANSPORT_FIELD_NAMES["buyer_name"]: buyer.get("name"),
        TRANSPORT_FIELD_NAMES["buyer_tax_id"]: buyer.get("tax_id"),
        TRANSPORT_FIELD_NAMES["passenger_name"]: passenger.get("name"),
        TRANSPORT_FIELD_NAMES["transport_number"]: travel.get("transport_number"),
        TRANSPORT_FIELD_NAMES["from_station"]: travel.get("from_station"),
        TRANSPORT_FIELD_NAMES["to_station"]: travel.get("to_station"),
        TRANSPORT_FIELD_NAMES["travel_date"]: _date_to_bitable_timestamp(travel.get("travel_date")),
        TRANSPORT_FIELD_NAMES["departure_time"]: travel.get("departure_time"),
        TRANSPORT_FIELD_NAMES["seat_no"]: passenger.get("seat_no"),
        TRANSPORT_FIELD_NAMES["seat_class"]: passenger.get("seat_class"),
        TRANSPORT_FIELD_NAMES["validation_status"]: validation.get("status"),
        TRANSPORT_FIELD_NAMES["needs_review"]: bool(review.get("needs_review")),
        TRANSPORT_FIELD_NAMES["review_reasons"]: _join_lines(review.get("reasons")),
        TRANSPORT_FIELD_NAMES["raw_json"]: _pretty_json(document),
    }
    return {"fields": _drop_none(fields)}


def build_expense_record(
    document: dict[str, Any],
    attachment_payload: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Map a skill document into the expense reimbursement table schema."""
    extraction = _ensure_dict(document.get("extraction"))
    doc = _ensure_dict(extraction.get("document"))
    buyer = _ensure_dict(extraction.get("buyer"))
    seller = _ensure_dict(extraction.get("seller"))
    validation = _ensure_dict(document.get("validation"))
    review = _ensure_dict(document.get("review"))
    line_items = extraction.get("line_items", [])
    first_line = line_items[0] if isinstance(line_items, list) and line_items else {}
    first_line = _ensure_dict(first_line)

    fields = {
        EXPENSE_FIELD_NAMES["doc_id"]: document.get("doc_id"),
        EXPENSE_FIELD_NAMES["expense_type"]: _map_expense_type(document.get("document_type")),
        EXPENSE_FIELD_NAMES["source_file_name"]: document.get("source_file_name"),
        EXPENSE_FIELD_NAMES["attachment"]: attachment_payload or [],
        EXPENSE_FIELD_NAMES["invoice_number"]: doc.get("invoice_number"),
        EXPENSE_FIELD_NAMES["issue_date"]: _date_to_bitable_timestamp(doc.get("issue_date")),
        EXPENSE_FIELD_NAMES["amount"]: doc.get("amount"),
        EXPENSE_FIELD_NAMES["currency"]: doc.get("currency"),
        EXPENSE_FIELD_NAMES["buyer_name"]: buyer.get("name"),
        EXPENSE_FIELD_NAMES["buyer_tax_id"]: buyer.get("tax_id"),
        EXPENSE_FIELD_NAMES["seller_name"]: seller.get("name"),
        EXPENSE_FIELD_NAMES["seller_tax_id"]: seller.get("tax_id"),
        EXPENSE_FIELD_NAMES["item_name"]: first_line.get("item_name"),
        EXPENSE_FIELD_NAMES["quantity"]: first_line.get("quantity"),
        EXPENSE_FIELD_NAMES["unit_price"]: first_line.get("unit_price"),
        EXPENSE_FIELD_NAMES["line_amount"]: first_line.get("line_amount"),
        EXPENSE_FIELD_NAMES["tax_rate"]: first_line.get("tax_rate"),
        EXPENSE_FIELD_NAMES["tax_amount"]: first_line.get("tax_amount"),
        EXPENSE_FIELD_NAMES["line_items_json"]: _pretty_json(line_items),
        EXPENSE_FIELD_NAMES["validation_status"]: validation.get("status"),
        EXPENSE_FIELD_NAMES["needs_review"]: bool(review.get("needs_review")),
        EXPENSE_FIELD_NAMES["review_reasons"]: _join_lines(review.get("reasons")),
        EXPENSE_FIELD_NAMES["raw_json"]: _pretty_json(document),
    }
    return {"fields": _drop_none(fields)}


def _resolve_secret(bitable: dict[str, Any], key: str) -> str:
    direct_value = bitable.get(key)
    if direct_value not in (None, ""):
        return str(direct_value)

    env_name = bitable.get(f"{key}_env")
    if env_name:
        return os.getenv(str(env_name), "")
    return ""


def _build_attachment_index(attachment_paths: list[str]) -> dict[str, str]:
    index: dict[str, str] = {}
    for raw_path in attachment_paths:
        path = Path(str(raw_path))
        if not path.exists():
            continue
        index[path.name] = str(path)
    return index


def _build_attachment_field(
    *,
    document: dict[str, Any],
    settings: BitableSettings,
    access_token: str,
    attachment_index: dict[str, str],
) -> list[dict[str, Any]]:
    source_path = str(document.get("source_file_path") or "").strip()
    if not source_path:
        source_name = str(document.get("source_file_name") or "").strip()
        source_path = attachment_index.get(source_name, "")

    if not source_path:
        return []

    if settings.dry_run:
        return [{"name": Path(source_path).name}]

    uploaded = upload_attachment(
        settings=settings,
        access_token=access_token,
        file_path=source_path,
    )
    return [{"file_token": uploaded["file_token"], "name": uploaded["name"]}]


def _map_expense_type(document_type: Any) -> str:
    value = str(document_type or "unknown")
    if value in TRANSPORTATION_TYPES:
        return "交通报销"

    mapping = {
        "conference_fee": "会议报销",
        "accommodation_fee": "酒店报销",
        "catering_fee": "餐饮报销",
        "office_supply_fee": "办公报销",
        "vat_invoice": "费用报销",
        "unknown": "费用报销",
    }
    return mapping.get(value, "费用报销")


def _date_to_bitable_timestamp(value: Any) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None
    return int(parsed.timestamp() * 1000)


def _drop_none(fields: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        cleaned[key] = value
    return cleaned


def _chunk_records(records: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [records[index : index + size] for index in range(0, len(records), size)]


def _join_lines(values: Any) -> str:
    if not isinstance(values, list):
        return str(values or "")
    return "\n".join(str(item) for item in values if str(item).strip())


def _pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _ensure_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    merged_headers = {
        "Content-Type": "application/json; charset=utf-8",
        **(headers or {}),
    }
    req = request.Request(url, data=body, headers=merged_headers, method="POST")
    return _read_json_response(req)


def _post_multipart(
    url: str,
    *,
    fields: dict[str, str],
    file_field_name: str,
    file_name: str,
    file_bytes: bytes,
    content_type: str,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    boundary = f"----OpenClawBoundary{uuid.uuid4().hex}"
    body = bytearray()

    for key, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8")
        )
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="{file_field_name}"; '
            f'filename="{file_name}"\r\n'
        ).encode("utf-8")
    )
    body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
    body.extend(file_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    merged_headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        **(headers or {}),
    }
    req = request.Request(url, data=bytes(body), headers=merged_headers, method="POST")
    return _read_json_response(req)


def _read_json_response(req: request.Request) -> dict[str, Any]:
    try:
        with request.urlopen(req, timeout=60) as response:
            raw_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise BitableSyncError(f"Feishu API error {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise BitableSyncError(f"Failed to reach Feishu API: {exc}") from exc

    payload = json.loads(raw_body or "{}")
    code = int(payload.get("code", 0) or 0)
    if code != 0:
        message = payload.get("msg") or payload.get("message") or "unknown error"
        raise BitableSyncError(f"Feishu API returned code {code}: {message}")
    return payload
