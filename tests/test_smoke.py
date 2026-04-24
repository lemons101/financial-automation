from __future__ import annotations

import os
import shutil
import textwrap
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from src.ingest import load_input_documents
from src.main import load_app_config
from src.ocr_extract import parse_fields_from_text
from src.output_formatter import (
    format_skill_document,
    format_skill_review_queue,
    format_skill_run_result,
)
from src.skill_entry import create_job_workspace, materialize_attachments, run_skill_job
from src.sync_bitable import (
    BitableSettings,
    build_expense_record,
    build_transport_record,
    load_bitable_settings,
    sync_skill_result_to_bitable,
)
from src.validate import validate_documents


def _make_test_workspace() -> Path:
    sandbox_root = Path(__file__).resolve().parent.parent / ".tmp_tests"
    sandbox_root.mkdir(parents=True, exist_ok=True)
    workspace = sandbox_root / f"test_{uuid.uuid4().hex}"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


class PathResolutionSmokeTest(unittest.TestCase):
    def test_relative_paths_are_resolved_from_project_root(self) -> None:
        project_root = _make_test_workspace()
        self.addCleanup(lambda: shutil.rmtree(project_root, ignore_errors=True))
        config_dir = project_root / "config"
        config_dir.mkdir()

        config_path = config_dir / "app_config.yaml"
        config_path.write_text(
            textwrap.dedent(
                """
                paths:
                  input_dir: runtime/inbox
                  output_dir: runtime/output
                  runtime_dir: runtime
                ocr:
                  rapidocr:
                    model_root_dir: runtime/models/rapidocr
                validate:
                  rules_file: config/rules.yaml
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        config, detected_root = load_app_config(config_path)
        self.assertEqual(detected_root, project_root.resolve())
        self.assertEqual(
            config["paths"]["input_dir"],
            str((project_root / "runtime/inbox").resolve()),
        )
        self.assertEqual(
            config["ocr"]["rapidocr"]["model_root_dir"],
            str((project_root / "runtime/models/rapidocr").resolve()),
        )

    def test_openclaw_project_root_override(self) -> None:
        workspace = _make_test_workspace()
        self.addCleanup(lambda: shutil.rmtree(workspace, ignore_errors=True))
        config_dir = workspace / "proj" / "config"
        config_dir.mkdir(parents=True)
        override_root = workspace / "override_root"
        override_root.mkdir()

        config_path = config_dir / "app_config.yaml"
        config_path.write_text(
            "paths:\n  input_dir: runtime/inbox\n",
            encoding="utf-8",
        )

        old_value = os.environ.get("OPENCLAW_PROJECT_ROOT")
        os.environ["OPENCLAW_PROJECT_ROOT"] = str(override_root)
        try:
            config, detected_root = load_app_config(config_path)
        finally:
            if old_value is None:
                os.environ.pop("OPENCLAW_PROJECT_ROOT", None)
            else:
                os.environ["OPENCLAW_PROJECT_ROOT"] = old_value

        self.assertEqual(detected_root, override_root.resolve())
        self.assertEqual(
            config["paths"]["input_dir"],
            str((override_root / "runtime/inbox").resolve()),
        )


class IngestSmokeTest(unittest.TestCase):
    def test_ingest_filters_and_collects_metadata(self) -> None:
        root = _make_test_workspace()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        inbox = root / "runtime" / "inbox"
        inbox.mkdir(parents=True)

        (inbox / "ok_invoice.pdf").write_bytes(b"fake-pdf")
        (inbox / "ok_image.JPG").write_bytes(b"fake-image")
        (inbox / "note.txt").write_text("not supported", encoding="utf-8")
        (inbox / "empty.png").write_bytes(b"")
        (inbox / "~$tmp.pdf").write_bytes(b"temp")

        config = {"paths": {"input_dir": str(inbox)}}
        documents, report = load_input_documents(config)

        self.assertEqual(report["total_seen"], 5)
        self.assertEqual(report["accepted"], 2)
        self.assertEqual(report["skipped"], 3)
        self.assertEqual(report["skip_reasons"]["unsupported_ext"], 1)
        self.assertEqual(report["skip_reasons"]["empty_file"], 1)
        self.assertEqual(report["skip_reasons"]["temp_file"], 1)

        self.assertEqual(len(documents), 2)
        self.assertIn("doc_id", documents[0])
        self.assertIn("file_path", documents[0])
        self.assertIn("modified_at", documents[0])

    def test_ingest_handles_missing_input_dir(self) -> None:
        documents, report = load_input_documents({"paths": {"input_dir": "D:/missing/path"}})
        self.assertEqual(documents, [])
        self.assertEqual(report["accepted"], 0)
        self.assertEqual(report["total_seen"], 0)
        self.assertTrue(report["errors"])


class OCRExtractSmokeTest(unittest.TestCase):
    def test_parse_accommodation_invoice_detail_fields(self) -> None:
        text = textwrap.dedent(
            """
            电子发票（普通发票）
            发票号码：24122000000046417589
            开票日期：2024 年 08 月 05 日
            购买方名称：复旦大学
            统一社会信用代码/纳税人识别号：12100000425006117P
            销售方名称：天津滨海一号酒店管理有限公司
            销售方统一社会信用代码/纳税人识别号：9112011656269768XB
            价税合计（小写）：￥924.00
            * 住宿服务 * 住宿费 6%871.70 52.30290.5660377358493
            """
        ).strip()

        parsed = parse_fields_from_text(text, default_currency="CNY")
        self.assertEqual(parsed["invoice_number"], "24122000000046417589")
        self.assertEqual(parsed["issue_date"], "2024-08-05")
        self.assertEqual(parsed["amount"], 924.0)
        self.assertEqual(parsed["currency"], "CNY")
        self.assertEqual(parsed["invoice_type"], "accommodation_fee")
        self.assertEqual(parsed["buyer_name"], "复旦大学")
        self.assertEqual(parsed["buyer_tax_id"], "12100000425006117P")
        self.assertEqual(parsed["vendor"], "天津滨海一号酒店管理有限公司")
        self.assertEqual(parsed["vendor_tax_id"], "9112011656269768XB")
        self.assertEqual(parsed["item_name"], "* 住宿服务 * 住宿费")
        self.assertEqual(parsed["quantity"], 3)
        self.assertAlmostEqual(parsed["unit_price"], 290.5660377358493)
        self.assertEqual(parsed["line_amount"], 871.7)
        self.assertEqual(parsed["tax_rate"], "6%")
        self.assertEqual(parsed["tax_amount"], 52.3)
        self.assertEqual(len(parsed["line_items"]), 1)
        self.assertFalse(parsed["needs_review"])

    def test_parse_conference_invoice_detail_fields(self) -> None:
        text = textwrap.dedent(
            """
            电子发票（普通发票）
            发票号码：24112000000114409809
            开票日期：2024年08月26日
            购买方名称：复旦大学
            统一社会信用代码/纳税人识别号：12100000425006117P
            销售方名称：北京冠大文化传播有限公司
            销售方统一社会信用代码/纳税人识别号：91110115MADQ08DP3H
            价税合计（小写）：￥5570.80
            * 会展服务 * 注册费 1%5515.64 55.165515.643564356441
            """
        ).strip()

        parsed = parse_fields_from_text(text, default_currency="CNY")
        self.assertEqual(parsed["invoice_type"], "conference_fee")
        self.assertEqual(parsed["item_name"], "* 会展服务 * 注册费")
        self.assertEqual(parsed["quantity"], 1)
        self.assertAlmostEqual(parsed["unit_price"], 5515.643564356441)
        self.assertEqual(parsed["line_amount"], 5515.64)
        self.assertEqual(parsed["tax_rate"], "1%")
        self.assertEqual(parsed["tax_amount"], 55.16)

    def test_parse_rail_ticket_fields(self) -> None:
        text = textwrap.dedent(
            """
            电子发票
            铁路电子客票
            发票号码：25339190041005476782
            开票日期：2025年10月16日
            杭州东站
            G240
            上海虹桥站
            2025年10月12日
            19:34开
            05车14F号
            二等座
            票价：￥87.00
            3607022001****0013
            林泓
            购票方名称：复旦大学
            统一社会信用代码：12100000425006117P
            """
        ).strip()

        parsed = parse_fields_from_text(text, default_currency="CNY")
        self.assertEqual(parsed["invoice_type"], "transportation_fee")
        self.assertEqual(parsed["buyer_name"], "复旦大学")
        self.assertEqual(parsed["buyer_tax_id"], "12100000425006117P")
        self.assertEqual(parsed["transport_number"], "G240")
        self.assertEqual(parsed["route"], "杭州东站->上海虹桥站")
        self.assertEqual(parsed["from_station"], "杭州东站")
        self.assertEqual(parsed["to_station"], "上海虹桥站")
        self.assertEqual(parsed["passenger_name"], "林泓")
        self.assertEqual(parsed["travel_date"], "2025-10-12")
        self.assertEqual(parsed["departure_time"], "19:34")
        self.assertEqual(parsed["seat_no"], "05车14F号")
        self.assertEqual(parsed["seat_class"], "二等座")
        self.assertIsNone(parsed["vendor"])
        self.assertIsNone(parsed["vendor_tax_id"])
        self.assertEqual(parsed["line_items"], [])


class ValidateSmokeTest(unittest.TestCase):
    def test_validate_documents_flags_missing_transport_fields(self) -> None:
        items = [
            {
                "doc_id": "doc-1",
                "source_file_name": "ticket.jpg",
                "invoice_number": "25339190041005476782",
                "issue_date": "2025-10-16",
                "amount": 87.0,
                "invoice_type": "transportation_fee",
                "buyer_name": "复旦大学",
                "buyer_tax_id": "12100000425006117P",
                "vendor": None,
                "vendor_tax_id": None,
                "route": None,
                "transport_number": None,
                "from_station": None,
                "to_station": None,
                "travel_date": None,
                "passenger_name": None,
                "ocr_source": "image_ocr",
                "ocr_status": "success",
                "extraction_confidence": 0.8375,
                "needs_review": False,
                "review_reasons": [],
            }
        ]
        config = {"validate": {"rules_file": "D:/Openclaw/Financial Automation/config/rules.yaml"}}

        validated_items, report = validate_documents(items, config)

        self.assertEqual(report["error_docs"], 1)
        self.assertEqual(validated_items[0]["compliance_status"], "error")
        finding_codes = {finding["code"] for finding in validated_items[0]["validation_findings"]}
        self.assertIn("missing_required_field", finding_codes)
        self.assertTrue(validated_items[0]["needs_review"])

    def test_validate_documents_flags_consistency_mismatches(self) -> None:
        items = [
            {
                "doc_id": "doc-2",
                "source_file_name": "conference.pdf",
                "invoice_number": "24112000000114409809",
                "issue_date": "2024-08-26",
                "amount": 100.0,
                "invoice_type": "conference_fee",
                "buyer_name": "复旦大学",
                "vendor": "北京冠大文化传播有限公司",
                "quantity": 2,
                "unit_price": 30.0,
                "line_amount": 70.0,
                "tax_amount": 20.0,
                "line_items": [
                    {
                        "item_name": "注册费",
                        "quantity": 2,
                        "unit_price": 30.0,
                        "line_amount": 70.0,
                        "tax_amount": 20.0,
                    }
                ],
                "ocr_source": "pdf_text",
                "ocr_status": "success",
                "extraction_confidence": 0.9,
                "needs_review": False,
                "review_reasons": [],
            }
        ]
        config = {"validate": {"rules_file": "D:/Openclaw/Financial Automation/config/rules.yaml"}}

        validated_items, report = validate_documents(items, config)
        findings = validated_items[0]["validation_findings"]
        finding_codes = {finding["code"] for finding in findings}

        self.assertEqual(report["warning_docs"], 1)
        self.assertEqual(validated_items[0]["compliance_status"], "warning")
        self.assertIn("line_item_mismatch", finding_codes)
        self.assertIn("invoice_total_mismatch", finding_codes)
        self.assertTrue(validated_items[0]["needs_review"])
        self.assertIn("validation_consistency_check_failed", validated_items[0]["review_reasons"])

    def test_validate_documents_passes_consistent_invoice(self) -> None:
        items = [
            {
                "doc_id": "doc-3",
                "source_file_name": "hotel.pdf",
                "invoice_number": "24122000000046417589",
                "issue_date": "2024-08-05",
                "amount": 924.0,
                "invoice_type": "accommodation_fee",
                "buyer_name": "复旦大学",
                "vendor": "天津滨海一号酒店管理有限公司",
                "quantity": 3,
                "unit_price": 290.5660377358493,
                "line_amount": 871.7,
                "tax_amount": 52.3,
                "line_items": [
                    {
                        "item_name": "住宿费",
                        "quantity": 3,
                        "unit_price": 290.5660377358493,
                        "line_amount": 871.7,
                        "tax_amount": 52.3,
                    }
                ],
                "ocr_source": "pdf_text",
                "ocr_status": "success",
                "extraction_confidence": 0.9,
                "needs_review": False,
                "review_reasons": [],
            }
        ]
        config = {"validate": {"rules_file": "D:/Openclaw/Financial Automation/config/rules.yaml"}}

        validated_items, report = validate_documents(items, config)

        self.assertEqual(report["pass_docs"], 1)
        self.assertEqual(validated_items[0]["compliance_status"], "pass")
        self.assertEqual(validated_items[0]["validation_findings"], [])
        self.assertFalse(validated_items[0]["needs_review"])


class OutputFormatterSmokeTest(unittest.TestCase):
    def test_format_invoice_skill_document(self) -> None:
        item = {
            "doc_id": "doc-invoice",
            "source_file_name": "hotel.pdf",
            "source_file_path": "D:/Openclaw/Financial Automation/runtime/sample_run_input/hotel.pdf",
            "invoice_type": "accommodation_fee",
            "invoice_number": "24122000000046417589",
            "issue_date": "2024-08-05",
            "amount": 924.0,
            "currency": "CNY",
            "buyer_name": "复旦大学",
            "buyer_tax_id": "12100000425006117P",
            "vendor": "天津滨海一号酒店管理有限公司",
            "vendor_tax_id": "9112011656269768XB",
            "item_name": "住宿费",
            "line_items": [
                {
                    "item_name": "住宿费",
                    "quantity": 3,
                    "unit_price": 290.5660377358493,
                    "line_amount": 871.7,
                    "tax_rate": "6%",
                    "tax_amount": 52.3,
                }
            ],
            "compliance_status": "pass",
            "validation_findings": [],
            "needs_review": False,
            "review_reasons": [],
            "extraction_confidence": 0.9,
            "ocr_status": "success",
        }

        formatted = format_skill_document(item)

        self.assertEqual(formatted["document_type"], "accommodation_fee")
        self.assertEqual(formatted["extraction"]["document"]["invoice_number"], "24122000000046417589")
        self.assertEqual(formatted["extraction"]["buyer"]["name"], "复旦大学")
        self.assertEqual(formatted["extraction"]["seller"]["name"], "天津滨海一号酒店管理有限公司")
        self.assertEqual(formatted["extraction"]["line_items"][0]["item_name"], "住宿费")
        self.assertEqual(formatted["validation"]["status"], "pass")
        self.assertFalse(formatted["review"]["needs_review"])

    def test_format_rail_ticket_skill_document(self) -> None:
        item = {
            "doc_id": "doc-rail",
            "source_file_name": "ticket.jpg",
            "source_file_path": "D:/Openclaw/Financial Automation/runtime/sample_run_input/ticket.jpg",
            "invoice_type": "transportation_fee",
            "invoice_number": "25339190041005476782",
            "issue_date": "2025-10-16",
            "amount": 87.0,
            "currency": "CNY",
            "buyer_name": "复旦大学",
            "buyer_tax_id": "12100000425006117P",
            "transport_number": "G240",
            "from_station": "杭州东站",
            "to_station": "上海虹桥站",
            "route": "杭州东站->上海虹桥站",
            "travel_date": "2025-10-12",
            "departure_time": "19:34",
            "passenger_name": "林泓",
            "seat_no": "05车14F号",
            "seat_class": "二等座",
            "compliance_status": "pass",
            "validation_findings": [],
            "needs_review": True,
            "review_reasons": ["image_ocr_requires_review"],
            "extraction_confidence": 0.875,
            "ocr_status": "success",
        }

        formatted = format_skill_document(item)

        self.assertEqual(formatted["document_type"], "transportation_fee")
        self.assertEqual(formatted["extraction"]["travel"]["transport_number"], "G240")
        self.assertEqual(formatted["extraction"]["travel"]["route"], "杭州东站->上海虹桥站")
        self.assertEqual(formatted["extraction"]["passenger"]["name"], "林泓")
        self.assertEqual(formatted["review"]["reasons"], ["image_ocr_requires_review"])

    def test_format_skill_review_queue(self) -> None:
        items = [
            {
                "doc_id": "doc-rail",
                "source_file_name": "ticket.jpg",
                "invoice_type": "transportation_fee",
                "invoice_number": "25339190041005476782",
                "issue_date": "2025-10-16",
                "amount": 87.0,
                "buyer_name": "复旦大学",
                "transport_number": "G240",
                "route": "杭州东站->上海虹桥站",
                "travel_date": "2025-10-12",
                "passenger_name": "林泓",
                "needs_review": True,
                "review_reasons": ["image_ocr_requires_review"],
                "compliance_status": "pass",
                "validation_findings": [],
            },
            {
                "doc_id": "doc-pass",
                "source_file_name": "hotel.pdf",
                "invoice_type": "accommodation_fee",
                "needs_review": False,
            },
        ]

        queue = format_skill_review_queue(items)

        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["doc_id"], "doc-rail")
        self.assertEqual(queue[0]["review"]["reasons"], ["image_ocr_requires_review"])
        self.assertEqual(queue[0]["summary"]["transport_number"], "G240")

    def test_format_skill_run_result(self) -> None:
        documents = [{"doc_id": "doc-1"}, {"doc_id": "doc-2"}]
        review_queue = [
            {
                "doc_id": "doc-2",
                "source_file_name": "ticket.jpg",
                "document_type": "transportation_fee",
                "review": {"reasons": ["image_ocr_requires_review"]},
                "summary": {
                    "document": {
                        "invoice_number": "25339190041005476782",
                        "amount": 87.0,
                    }
                },
            }
        ]
        payload = format_skill_run_result(
            app_name="financial-automation",
            run_id="20260424_999999",
            input_dir="D:/Openclaw/Financial Automation/runtime/inbox",
            output_dir="D:/Openclaw/Financial Automation/runtime/output/20260424_999999",
            documents=documents,
            review_queue=review_queue,
            counts={
                "documents_seen": 2,
                "documents_accepted": 2,
                "documents_extracted": 2,
                "documents_for_review": 1,
                "documents_pass": 1,
                "documents_warning": 1,
                "documents_error": 0,
            },
        )

        self.assertEqual(payload["run_id"], "20260424_999999")
        self.assertEqual(payload["summary"]["documents_for_review"], 1)
        self.assertIn("Processed 2 documents", payload["user_summary"]["headline"])
        self.assertEqual(payload["highlights"]["review_queue_count"], 1)
        self.assertEqual(
            payload["highlights"]["review_items"][0]["reasons"],
            ["image_ocr_requires_review"],
        )
        self.assertEqual(len(payload["documents"]), 2)
        self.assertEqual(len(payload["review_queue"]), 1)


class SkillEntrySmokeTest(unittest.TestCase):
    def _make_workspace(self) -> Path:
        sandbox_root = Path(__file__).resolve().parent.parent / ".tmp_tests"
        sandbox_root.mkdir(parents=True, exist_ok=True)
        workspace = sandbox_root / f"skill_entry_{uuid.uuid4().hex}"
        workspace.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(workspace, ignore_errors=True))
        return workspace

    def test_create_job_workspace_builds_expected_dirs(self) -> None:
        temp_dir = self._make_workspace()
        runtime_dir = temp_dir / "runtime"
        config = {"paths": {"runtime_dir": str(runtime_dir)}}

        workspace = create_job_workspace(config, temp_dir, job_id="job_demo")

        self.assertEqual(workspace["job_id"], "job_demo")
        self.assertTrue(Path(str(workspace["job_dir"])).exists())
        self.assertTrue(Path(str(workspace["input_dir"])).exists())
        self.assertTrue(Path(str(workspace["output_dir"])).exists())

    def test_materialize_attachments_writes_supported_files(self) -> None:
        temp_dir = self._make_workspace()
        input_dir = temp_dir / "inbox"
        source_file = temp_dir / "ticket.jpg"
        source_file.write_bytes(b"image-bytes")

        saved = materialize_attachments(
            [
                {"file_name": "invoice.pdf", "content_bytes": b"pdf-bytes"},
                {"file_name": "ticket.jpg", "source_path": str(source_file)},
                {"file_name": "note.txt", "content_bytes": b"skip-me"},
                {"file_name": "invoice.pdf", "content_bytes": b"pdf-bytes-2"},
            ],
            input_dir,
        )

        self.assertEqual(len(saved), 3)
        self.assertTrue((input_dir / "invoice.pdf").exists())
        self.assertTrue((input_dir / "invoice_1.pdf").exists())
        self.assertTrue((input_dir / "ticket.jpg").exists())
        self.assertFalse((input_dir / "note.txt").exists())

    def test_run_skill_job_returns_skill_result_with_job_info(self) -> None:
        project_root = self._make_workspace()
        config_dir = project_root / "config"
        runtime_dir = project_root / "runtime"
        config_dir.mkdir()
        runtime_dir.mkdir()

        config_path = config_dir / "app_config.yaml"
        config_path.write_text(
            textwrap.dedent(
                """
                paths:
                  input_dir: runtime/inbox
                  output_dir: runtime/output
                  runtime_dir: runtime
                validate:
                  rules_file: config/rules.yaml
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        fake_result = {
            "status": "completed",
            "summary": {"documents_extracted": 1},
            "documents": [],
        }

        with patch("src.skill_entry.run_pipeline_for_job") as mocked_run, patch(
            "src.skill_entry.load_skill_result",
            return_value=fake_result.copy(),
        ) as mocked_load:
            mocked_run.return_value = {
                "run_id": "20260424_000001",
                "output": {
                    "run_dir": str(project_root / "runtime" / "jobs" / "job_fake" / "output" / "20260424_000001")
                },
            }

            result = run_skill_job(
                attachments=[{"file_name": "ticket.jpg", "content_bytes": b"fake-image"}],
                config_path=config_path,
            )

        mocked_run.assert_called_once()
        mocked_load.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertIn("job", result)
        self.assertEqual(result["bitable_sync"]["status"], "disabled")
        self.assertEqual(len(result["job"]["saved_files"]), 1)
        self.assertTrue(result["job"]["saved_files"][0].endswith("ticket.jpg"))


class SyncBitableSmokeTest(unittest.TestCase):
    def test_load_bitable_settings_prefers_environment_overrides(self) -> None:
        old_values = {
            "FEISHU_APP_ID": os.environ.get("FEISHU_APP_ID"),
            "FEISHU_APP_SECRET": os.environ.get("FEISHU_APP_SECRET"),
            "FEISHU_BITABLE_APP_TOKEN": os.environ.get("FEISHU_BITABLE_APP_TOKEN"),
            "FEISHU_BITABLE_TRANSPORT_TABLE": os.environ.get("FEISHU_BITABLE_TRANSPORT_TABLE"),
            "FEISHU_BITABLE_EXPENSE_TABLE": os.environ.get("FEISHU_BITABLE_EXPENSE_TABLE"),
        }
        os.environ["FEISHU_APP_ID"] = "cli_app_id"
        os.environ["FEISHU_APP_SECRET"] = "cli_secret"
        os.environ["FEISHU_BITABLE_APP_TOKEN"] = "cli_app_token"
        os.environ["FEISHU_BITABLE_TRANSPORT_TABLE"] = "cli_transport"
        os.environ["FEISHU_BITABLE_EXPENSE_TABLE"] = "cli_expense"
        try:
            settings = load_bitable_settings(
                {
                    "sync": {
                        "bitable": {
                            "enabled": True,
                            "dry_run": True,
                            "app_id_env": "FEISHU_APP_ID",
                            "app_secret_env": "FEISHU_APP_SECRET",
                            "app_token_env": "FEISHU_BITABLE_APP_TOKEN",
                            "transport_table_id_env": "FEISHU_BITABLE_TRANSPORT_TABLE",
                            "expense_table_id_env": "FEISHU_BITABLE_EXPENSE_TABLE",
                        }
                    }
                }
            )
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertEqual(settings.app_id, "cli_app_id")
        self.assertEqual(settings.transport_table_id, "cli_transport")
        self.assertEqual(settings.expense_table_id, "cli_expense")

    def test_build_transport_record_maps_fields(self) -> None:
        document = {
            "doc_id": "doc-rail",
            "document_type": "transportation_fee",
            "source_file_name": "ticket.jpg",
            "extraction": {
                "document": {
                    "invoice_number": "25339190041005476782",
                    "amount": 87.0,
                    "currency": "CNY",
                },
                "buyer": {"name": "Fudan", "tax_id": "12100000425006117P"},
                "travel": {
                    "transport_number": "G240",
                    "from_station": "Hangzhou East",
                    "to_station": "Shanghai Hongqiao",
                    "travel_date": "2025-10-12",
                    "departure_time": "19:34",
                },
                "passenger": {
                    "name": "Lemon",
                    "seat_no": "05车14F号",
                    "seat_class": "二等座",
                },
            },
            "validation": {"status": "pass"},
            "review": {"needs_review": True, "reasons": ["image_ocr_requires_review"]},
        }

        record = build_transport_record(document, [{"file_token": "file-token"}])
        fields = record["fields"]

        self.assertEqual(fields["报销类型"], "交通报销")
        self.assertEqual(fields["票据号码"], "25339190041005476782")
        self.assertEqual(fields["购票主体"], "Fudan")
        self.assertEqual(fields["车次"], "G240")
        self.assertEqual(fields["票据附件"][0]["file_token"], "file-token")
        self.assertTrue(fields["是否复核"])

    def test_build_expense_record_maps_first_line_item_and_json(self) -> None:
        document = {
            "doc_id": "doc-expense",
            "document_type": "conference_fee",
            "source_file_name": "invoice.pdf",
            "extraction": {
                "document": {
                    "invoice_number": "24112000000114409809",
                    "issue_date": "2024-08-26",
                    "amount": 5570.80,
                    "currency": "CNY",
                },
                "buyer": {"name": "Fudan", "tax_id": "12100000425006117P"},
                "seller": {"name": "Vendor", "tax_id": "911111111111111111"},
                "line_items": [
                    {
                        "item_name": "会议费",
                        "quantity": 1,
                        "unit_price": 5515.64,
                        "line_amount": 5515.64,
                        "tax_rate": "1%",
                        "tax_amount": 55.16,
                    },
                    {
                        "item_name": "服务费",
                        "quantity": 1,
                        "unit_price": 10.00,
                        "line_amount": 10.00,
                        "tax_rate": "0%",
                        "tax_amount": 0.00,
                    },
                ],
            },
            "validation": {"status": "warning"},
            "review": {"needs_review": False, "reasons": []},
        }

        record = build_expense_record(document, [{"file_token": "file-token"}])
        fields = record["fields"]

        self.assertEqual(fields["报销类型"], "会议报销")
        self.assertEqual(fields["项目名称"], "会议费")
        self.assertEqual(fields["税率"], "1%")
        self.assertIn("服务费", fields["项目明细JSON"])

    def test_sync_skill_result_to_bitable_supports_dry_run(self) -> None:
        settings = BitableSettings(
            enabled=True,
            dry_run=True,
            endpoint="https://open.feishu.cn",
            batch_size=200,
            app_id="app_id",
            app_secret="app_secret",
            app_token="app_token",
            transport_table_id="transport_table",
            expense_table_id="expense_table",
        )
        skill_result = {
            "documents": [
                {
                    "doc_id": "doc-rail",
                    "document_type": "transportation_fee",
                    "source_file_name": "ticket.jpg",
                    "extraction": {
                        "document": {"invoice_number": "123", "amount": 87.0, "currency": "CNY"},
                        "buyer": {"name": "Fudan", "tax_id": "tax"},
                        "travel": {"transport_number": "G240"},
                        "passenger": {"name": "Lemon"},
                    },
                    "validation": {"status": "pass"},
                    "review": {"needs_review": False, "reasons": []},
                },
                {
                    "doc_id": "doc-expense",
                    "document_type": "conference_fee",
                    "source_file_name": "invoice.pdf",
                    "extraction": {
                        "document": {
                            "invoice_number": "456",
                            "issue_date": "2024-08-26",
                            "amount": 100.0,
                            "currency": "CNY",
                        },
                        "buyer": {"name": "Fudan", "tax_id": "tax"},
                        "seller": {"name": "Vendor", "tax_id": "tax2"},
                        "line_items": [{"item_name": "会议费"}],
                    },
                    "validation": {"status": "warning"},
                    "review": {"needs_review": True, "reasons": ["manual_review"]},
                },
            ]
        }

        summary = sync_skill_result_to_bitable(skill_result, settings)

        self.assertEqual(summary["status"], "dry_run")
        self.assertEqual(summary["tables"]["transport"]["records_prepared"], 1)
        self.assertEqual(summary["tables"]["expense"]["records_prepared"], 1)
        self.assertEqual(summary["tables"]["transport"]["preview"][0]["fields"]["报销类型"], "交通报销")


if __name__ == "__main__":
    unittest.main()
