from __future__ import annotations

from typing import Any


TRANSPORT_TARGET = "transport"
EXPENSE_TARGET = "expense"
PRIMARY_FIELD = "doc_id"


def pick_reusable_record_id(records: list[dict[str, Any]]) -> str | None:
    for record in records:
        if not isinstance(record, dict):
            continue
        fields = record.get("fields")
        if not isinstance(fields, dict):
            continue
        primary_value = fields.get(PRIMARY_FIELD)
        if primary_value in (None, "", []):
            record_id = record.get("record_id") or record.get("id")
            if isinstance(record_id, str) and record_id.strip():
                return record_id.strip()
    return None


def choose_bitable_write_action(existing_records: list[dict[str, Any]]) -> dict[str, Any]:
    reusable = pick_reusable_record_id(existing_records)
    if reusable:
        return {"action": "update", "record_id": reusable}
    return {"action": "create"}
