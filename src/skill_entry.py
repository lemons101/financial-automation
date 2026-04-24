from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .main import DEFAULT_CONFIG_PATH, load_app_config, run_pipeline
    from .sync_bitable import sync_skill_result_with_config
except ImportError:  # pragma: no cover - supports running as a script.
    from main import DEFAULT_CONFIG_PATH, load_app_config, run_pipeline
    from sync_bitable import sync_skill_result_with_config


SUPPORTED_SKILL_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}


def run_skill_job(
    attachments: list[dict[str, Any]],
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the existing finance pipeline from a skill-friendly attachment payload."""
    config_file = config_path or DEFAULT_CONFIG_PATH
    config, project_root = load_app_config(config_file)
    workspace = create_job_workspace(config, project_root)
    saved_files = materialize_attachments(attachments, workspace["input_dir"])
    if not saved_files:
        raise ValueError("No supported attachments were provided to the skill job.")

    summary = run_pipeline_for_job(
        config=config,
        project_root=project_root,
        input_dir=workspace["input_dir"],
        output_dir=workspace["output_dir"],
    )
    result = load_skill_result(summary["output"]["run_dir"])
    result["job"] = {
        "job_id": workspace["job_id"],
        "job_dir": str(workspace["job_dir"]),
        "input_dir": str(workspace["input_dir"]),
        "output_dir": str(workspace["output_dir"]),
        "saved_files": [str(path) for path in saved_files],
    }
    result["bitable_sync"] = sync_skill_result_with_config(
        result,
        config,
        attachment_paths=[str(path) for path in saved_files],
    )
    result["bitable_write_plan"] = build_bitable_write_plan(
        result,
        attachment_paths=[str(path) for path in saved_files],
    )
    return result


def create_job_workspace(
    config: dict[str, Any],
    project_root: Path,
    job_id: str | None = None,
) -> dict[str, Path | str]:
    """Create an isolated job workspace under runtime/jobs."""
    runtime_root_value = config.get("paths", {}).get("runtime_dir")
    runtime_root = Path(str(runtime_root_value)) if runtime_root_value else project_root / "runtime"
    jobs_root = runtime_root / "jobs"
    resolved_job_id = job_id or _make_job_id()
    job_dir = jobs_root / resolved_job_id
    input_dir = job_dir / "inbox"
    output_dir = job_dir / "output"

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    return {
        "job_id": resolved_job_id,
        "job_dir": job_dir,
        "input_dir": input_dir,
        "output_dir": output_dir,
    }


def materialize_attachments(
    attachments: list[dict[str, Any]],
    input_dir: str | Path,
) -> list[Path]:
    """Write supported attachments into the job inbox."""
    target_dir = Path(input_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    for attachment in attachments:
        file_name = _normalize_attachment_name(attachment)
        if not file_name:
            continue

        extension = Path(file_name).suffix.lower()
        if extension not in SUPPORTED_SKILL_EXTENSIONS:
            continue

        payload = _read_attachment_bytes(attachment)
        if payload is None:
            continue

        target_path = _resolve_unique_path(target_dir / file_name)
        target_path.write_bytes(payload)
        saved_paths.append(target_path)

    return saved_paths


def run_pipeline_for_job(
    *,
    config: dict[str, Any],
    project_root: Path,
    input_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Run the shared pipeline against a prepared job workspace."""
    job_config = copy.deepcopy(config)
    job_config.setdefault("paths", {})
    job_config["paths"]["input_dir"] = str(Path(input_dir))
    job_config["paths"]["output_dir"] = str(Path(output_dir))
    return run_pipeline(job_config, project_root)


def load_skill_result(run_dir: str | Path) -> dict[str, Any]:
    """Load the formatted skill result for a completed run."""
    run_path = Path(run_dir)
    skill_result_path = run_path / "skill_result.json"
    return _read_json(skill_result_path)


def build_bitable_write_plan(
    skill_result: dict[str, Any],
    *,
    attachment_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Build a user-identity write plan for the current OpenClaw session."""
    try:
        from .sync_bitable import (
            TRANSPORTATION_TYPES,
            build_expense_record,
            build_transport_record,
        )
    except ImportError:  # pragma: no cover - supports running as a script.
        from sync_bitable import (  # type: ignore
            TRANSPORTATION_TYPES,
            build_expense_record,
            build_transport_record,
        )

    documents = skill_result.get("documents", [])
    plan = {
        "mode": "user_identity",
        "include_attachments": False,
        "records": [],
    }
    for document in documents:
        if not isinstance(document, dict):
            continue
        document_type = str(document.get("document_type") or "unknown")
        if document_type in TRANSPORTATION_TYPES:
            plan["records"].append(
                {
                    "target": "transport",
                    "fields": build_transport_record(document, []),
                }
            )
        else:
            plan["records"].append(
                {
                    "target": "expense",
                    "fields": build_expense_record(document, []),
                }
            )
    if attachment_paths:
        plan["attachment_paths"] = list(attachment_paths)
    return plan


def _make_job_id() -> str:
    return datetime.now(timezone.utc).strftime("job_%Y%m%d_%H%M%S_%f")


def _normalize_attachment_name(attachment: dict[str, Any]) -> str | None:
    raw_name = str(attachment.get("file_name") or "").strip()
    if not raw_name:
        return None
    return Path(raw_name).name


def _read_attachment_bytes(attachment: dict[str, Any]) -> bytes | None:
    if isinstance(attachment.get("content_bytes"), bytes):
        return attachment["content_bytes"]

    source_path = attachment.get("source_path")
    if source_path:
        return Path(str(source_path)).read_bytes()

    return None


def _resolve_unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    counter = 1
    while True:
        candidate = path.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _read_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))
