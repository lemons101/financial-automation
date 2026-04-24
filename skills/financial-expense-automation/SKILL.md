---
name: financial-expense-automation
description: Process uploaded expense attachments into structured finance results for reimbursement workflows. Use when users provide PDF, JPG, JPEG, or PNG receipts in OpenClaw or Feishu and need extracted invoice or rail-ticket fields, validation status, review queue output, or a skill-friendly batch result.
---

# Financial Expense Automation

## Overview

Run the local Financial Automation pipeline against uploaded receipts and return structured expense results.
Use this skill for the current first-version scope: normal electronic invoices and railway e-tickets.

## Repository Location

This skill expects the full project repository to exist on the same machine.

Resolve the project root in this order:

1. Use `FINANCIAL_AUTOMATION_ROOT` if it is set.
2. Otherwise check these common paths:
   - `~/projects/financial-automation`
   - `~/.openclaw/workspace/financial-automation`
   - `/root/projects/financial-automation`

If none of these paths exists, stop and tell the user the repository has not been deployed to the server yet.

After locating the repository root, use:
- `<repo_root>/src/skill_entry.py`
- `<repo_root>/config/app_config.yaml`

## Workflow

1. Locate the repository root first.
2. Convert incoming files into the attachment payload expected by `src/skill_entry.py`.
3. Call `run_skill_job(...)` instead of manually chaining ingest, OCR, validate, and formatter steps.
4. Use the returned `skill_result` payload as the main response object.
5. When summarizing for users, prefer `user_summary` and `highlights` over raw OCR fields.
6. When downstream systems need structured records, use `documents` and `review_queue`.

## Inputs

Build attachments as a list of dictionaries in one of these shapes:

```python
[
    {
        "file_name": "hotel_invoice.pdf",
        "content_bytes": b"...",
    },
    {
        "file_name": "ticket.jpg",
        "source_path": "D:/path/to/ticket.jpg",
    },
]
```

Supported file types:
- `.pdf`
- `.jpg`
- `.jpeg`
- `.png`

Ignore unsupported files instead of trying to force them through OCR.
If no supported files remain, stop and tell the user no valid expense attachments were provided.

## Entry Point

Use `<repo_root>/src/skill_entry.py` as the only skill execution entry point.

Primary call:

```python
from src.skill_entry import run_skill_job

result = run_skill_job(attachments)
```

Optional override:

```python
result = run_skill_job(
    attachments,
    config_path=f"{repo_root}/config/app_config.yaml",
)
```

Example repository root on a cloud server:

```python
repo_root = "/root/projects/financial-automation"
```

## Outputs

The returned object is the contents of `skill_result.json` plus job metadata.

Most important fields:
- `user_summary`
- `summary`
- `highlights`
- `documents`
- `review_queue`
- `job`

Use these output files only when deeper inspection is needed:
- `skill_json/*.json`
- `skill_review_queue.json`
- `skill_result.json`
- `run_summary.json`

## Deployment Note

Recommended cloud layout:

```text
/root/projects/financial-automation
~/.openclaw/workspace/skills/financial-expense-automation
```

The repository stores the pipeline code.
The skill directory stores the `SKILL.md` and agent metadata that tell OpenClaw how to use the pipeline.

## Current Scope

Supported document types:
- Normal electronic invoices
- Railway e-tickets

Current extraction highlights:
- Invoice number, issue date, amount, invoice type
- Buyer and seller identities for invoices
- Invoice line item totals, tax rate, tax amount
- Railway buyer, route, train number, passenger, travel date, departure time, seat fields
- Validation findings and review reasons

## Response Guidance

When replying in chat:
- Lead with `user_summary.headline`
- If `review_queue` is non-empty, call out each review item and its reasons
- For invoice requests, summarize buyer, seller, amount, and line item headline
- For rail tickets, summarize buyer, route, travel date, passenger, and seat info

When syncing to a downstream table:
- Use `documents` as the normalized structured payload
- Use `review_queue` for items that need manual follow-up
