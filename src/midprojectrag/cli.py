from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from midprojectrag.ingest.common import read_jsonl, require_within, write_json, write_jsonl
from midprojectrag.ingest.extract import extract_manifest
from midprojectrag.ingest.manifest import build_manifest
from midprojectrag.ingest.verify import verify_manifest


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _print_failure(error: str) -> None:
    print(json.dumps({"passed": False, "error": error}, sort_keys=True))


def _manifest_command(args: argparse.Namespace) -> int:
    data_dir = args.data_dir.resolve()
    csv_path = (args.csv_path or data_dir / "data_list.csv").resolve()
    raw_dir = (args.raw_dir or data_dir / "files").resolve()
    output = (args.output or data_dir / "private" / "manifest.jsonl").resolve()
    report_path = (args.report or output.with_name("manifest.join-report.json")).resolve()

    if not data_dir.is_dir() or not csv_path.is_file() or not raw_dir.is_dir():
        _print_failure("input_path_missing")
        return 2

    try:
        output = require_within(output, data_dir, "output_path_outside_data_dir")
        report_path = require_within(report_path, data_dir, "report_path_outside_data_dir")
        result = build_manifest(
            data_dir=data_dir,
            csv_path=csv_path,
            raw_dir=raw_dir,
            expected_documents=args.expected_documents,
            expected_hwp=args.expected_hwp,
            expected_pdf=args.expected_pdf,
        )
    except ValueError as error:
        error_code = str(error)
        if not error_code.endswith("_outside_data_dir"):
            error_code = "manifest_validation_failed"
        _print_failure(error_code)
        return 2
    except (OSError, UnicodeError):
        _print_failure("manifest_read_failed")
        return 2
    try:
        write_jsonl(output, result.entries)
        write_json(report_path, result.report)
    except OSError:
        _print_failure("manifest_write_failed")
        return 2
    summary = {
        "passed": result.passed,
        "snapshot_id": result.report["snapshot_id"],
        "counts": result.report["counts"],
        "error_codes": [issue["code"] for issue in result.report["errors"]],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if result.passed else 2


def _extract_command(args: argparse.Namespace) -> int:
    try:
        summary = extract_manifest(
            manifest_path=args.manifest.resolve(),
            data_dir=args.data_dir.resolve(),
            output_dir=args.output_dir.resolve(),
            output_manifest_path=args.output_manifest.resolve(),
            timeout_seconds=args.timeout_seconds,
        )
    except ValueError as error:
        error_code = str(error)
        if not error_code.endswith("_outside_data_dir"):
            error_code = "extract_validation_failed"
        _print_failure(error_code)
        return 3
    except (OSError, UnicodeError, json.JSONDecodeError):
        _print_failure("extract_read_failed")
        return 3
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status_counts"].get("failed", 0) == 0 else 3


def _verify_command(args: argparse.Namespace) -> int:
    try:
        entries = read_jsonl(args.manifest.resolve())
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        _print_failure("manifest_read_failed")
        return 4
    report = verify_manifest(
        entries,
        blocks_dir=args.blocks_dir.resolve() if args.blocks_dir else None,
        expected_documents=args.expected_documents,
        expected_hwp=args.expected_hwp,
        expected_pdf=args.expected_pdf,
        require_extracted=args.require_extracted,
        max_failed=args.max_failed,
    )
    if args.report:
        try:
            write_json(args.report.resolve(), report)
        except OSError:
            _print_failure("verify_report_write_failed")
            return 4
    summary = {
        "passed": report["passed"],
        "counts": report["counts"],
        "error_codes": [issue["code"] for issue in report["errors"]],
        "warning_codes": [issue["code"] for issue in report["warnings"]],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if report["passed"] else 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="midprojectrag")
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest = subparsers.add_parser("manifest", help="join CSV metadata to private source files")
    manifest.add_argument("--data-dir", type=Path, required=True)
    manifest.add_argument("--csv-path", type=Path)
    manifest.add_argument("--raw-dir", type=Path)
    manifest.add_argument("--output", type=Path)
    manifest.add_argument("--report", type=Path)
    manifest.add_argument("--expected-documents", type=_positive_int, default=100)
    manifest.add_argument("--expected-hwp", type=_positive_int, default=96)
    manifest.add_argument("--expected-pdf", type=_positive_int, default=4)
    manifest.set_defaults(handler=_manifest_command)

    extract = subparsers.add_parser("extract", help="extract stable source blocks")
    extract.add_argument("--manifest", type=Path, required=True)
    extract.add_argument("--data-dir", type=Path, required=True)
    extract.add_argument("--output-dir", type=Path, required=True)
    extract.add_argument("--output-manifest", type=Path, required=True)
    extract.add_argument("--timeout-seconds", type=_positive_int, default=120)
    extract.set_defaults(handler=_extract_command)

    verify = subparsers.add_parser("verify", help="verify inventory and extraction integrity")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--blocks-dir", type=Path)
    verify.add_argument("--report", type=Path)
    verify.add_argument("--expected-documents", type=_positive_int, default=100)
    verify.add_argument("--expected-hwp", type=_positive_int, default=96)
    verify.add_argument("--expected-pdf", type=_positive_int, default=4)
    verify.add_argument("--require-extracted", action="store_true")
    verify.add_argument("--max-failed", type=_positive_int, default=0)
    verify.set_defaults(handler=_verify_command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)
