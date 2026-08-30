from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Sequence

from midprojectrag.ingest.common import (
    canonical_json,
    read_jsonl,
    require_sha256,
    require_within,
    sha256_file,
    sha256_text,
    write_json,
    write_jsonl,
)
from midprojectrag.ingest.extract import extract_manifest
from midprojectrag.ingest.manifest import build_manifest
from midprojectrag.ingest.metadata_corrections import apply_metadata_corrections
from midprojectrag.ingest.verify import verify_manifest


_STACK_ARTIFACT_ROOTS = {
    "api": {
        "indexes": Path("private/indexes/api"),
        "caches": Path("private/caches/api"),
        "outputs": Path("private/outputs/api"),
    },
    "local": {
        "indexes": Path("private/indexes/local"),
        "caches": Path("private/caches/local"),
        "outputs": Path("private/outputs/local"),
    },
}

_API_EMBEDDING_MODELS = ("text-embedding-3-small", "text-embedding-3-large")
_API_GENERATOR_MODELS = ("gpt-5-mini", "gpt-5-nano")
_API_PROFILES = ("assignment", "personal_experimental")


def _allowlisted_model_env(
    name: str,
    *,
    choices: tuple[str, ...],
    default: str,
    error_code: str,
) -> str:
    value = os.getenv(name, default).strip()
    if value not in choices:
        raise ValueError(error_code)
    return value


def _require_stack_artifact_path(
    path: Path,
    data_dir: Path,
    *,
    stack_id: str,
    artifact_kind: str,
    error_code: str,
) -> Path:
    """Fail closed when a provider artifact crosses its private stack root."""

    try:
        relative_root = _STACK_ARTIFACT_ROOTS[stack_id][artifact_kind]
    except KeyError as error:
        raise RuntimeError("invalid_stack_artifact_configuration") from error
    stack_root = require_within(data_dir / relative_root, data_dir, error_code)
    return require_within(path, stack_root, error_code)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _strict_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _sha256_hex(value: str) -> str:
    try:
        return require_sha256(value, "must be 64 lowercase hex characters")
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _print_failure(error: str) -> None:
    print(json.dumps({"passed": False, "error": error}, sort_keys=True))


def _load_project_dotenv() -> None:
    """Load local secrets before provider or observability initialization.

    Existing process variables win. ``OPENAI_API_KEY_PRIVATE`` is a project
    alias for a personal account key and is copied into the standard OpenAI
    SDK variable only when ``OPENAI_API_KEY`` is empty. Values and paths are
    never logged.
    """

    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path, override=False)
    standard_key = os.getenv("OPENAI_API_KEY", "")
    private_key = os.getenv("OPENAI_API_KEY_PRIVATE", "")
    if not standard_key.strip() and private_key.strip():
        os.environ["OPENAI_API_KEY"] = private_key


def _safe_error_code(error: BaseException, fallback: str) -> str:
    """Return only a bounded machine code; never echo paths or provider text."""

    value = str(error)
    if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value):
        return value
    return fallback


def _safe_provider_error_code(error: BaseException, fallback: str) -> str:
    return {
        "RateLimitError": "provider_rate_limited",
        "APITimeoutError": "provider_timeout",
        "APIConnectionError": "provider_connection_failed",
        "AuthenticationError": "provider_authentication_failed",
        "PermissionDeniedError": "provider_permission_denied",
        "BadRequestError": "provider_request_rejected",
    }.get(type(error).__name__, fallback)


def _manifest_command(args: argparse.Namespace) -> int:
    data_dir = args.data_dir.resolve()
    default_csv_path = data_dir / "refined_data_list.csv"
    if not default_csv_path.is_file():
        default_csv_path = data_dir / "data_list.csv"
    csv_path = (args.csv_path or default_csv_path).resolve()
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


def _correct_metadata_command(args: argparse.Namespace) -> int:
    data_dir = args.data_dir.resolve()
    source_csv_path = (args.source_csv or data_dir / "data_list.csv").resolve()
    output_csv_path = (
        args.output or data_dir / "private" / "data_list.corrected.csv"
    ).resolve()
    report_path = (
        args.report or data_dir / "private" / "metadata-corrections.report.json"
    ).resolve()
    if (
        not data_dir.is_dir()
        or not source_csv_path.is_file()
        or not args.corrections.is_file()
    ):
        _print_failure("correction_input_path_missing")
        return 2
    try:
        report = apply_metadata_corrections(
            data_dir=data_dir,
            source_csv_path=source_csv_path,
            corrections_path=args.corrections.resolve(),
            output_csv_path=output_csv_path,
            report_path=report_path,
        )
    except ValueError as error:
        _print_failure(_safe_error_code(error, "correction_validation_failed"))
        return 2
    except (OSError, UnicodeError, json.JSONDecodeError):
        _print_failure("correction_io_failed")
        return 2
    summary = {
        "passed": True,
        "source_row_count": report["source_row_count"],
        "output_row_count": report["output_row_count"],
        "correction_count": report["correction_count"],
        "decision_counts": report["decision_counts"],
        "applied_field_counts": report["applied_field_counts"],
        "changed_field_counts": report["changed_field_counts"],
        "reason_counts": report["reason_counts"],
        "source_csv_sha256": report["source_csv_sha256"],
        "output_csv_sha256": report["output_csv_sha256"],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


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
        require_extracted=args.require_extracted or args.require_primary_hwp,
        require_primary_hwp=args.require_primary_hwp,
        expected_rhwp_sha256=args.rhwp_sha256,
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


def _visual_gold_validate_command(args: argparse.Namespace) -> int:
    """Validate private representative annotations without printing content."""

    from midprojectrag.ingest.visual_gold import validate_visual_gold

    try:
        data_dir = args.data_dir.resolve(strict=True)
        annotations_path = require_within(
            args.annotations.resolve(),
            data_dir,
            "visual_gold_path_outside_data_dir",
        )
        records = read_jsonl(annotations_path)
        result = validate_visual_gold(
            records,
            require_reviewed=not args.allow_draft,
            require_full_representative_gate=not args.partial,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        _print_failure(_safe_error_code(error, "visual_gold_validation_failed"))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _pdf_visual_v2_command(args: argparse.Namespace) -> int:
    """Materialize the four-document local PDF visual lane."""

    from midprojectrag.ingest.pdf_visual_runner import (
        run_pdf_visual_v2_from_manifest,
    )

    try:
        result = run_pdf_visual_v2_from_manifest(
            manifest_path=args.manifest.resolve(),
            data_dir=args.data_dir.resolve(),
            output_dir=args.output_dir.resolve(),
            private_root=(
                args.private_root.resolve() if args.private_root is not None else None
            ),
            render_scale=args.render_scale,
            expected_existing_artifact_set_id=args.expected_artifact_set_id,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        _print_failure(_safe_error_code(error, "pdf_visual_v2_failed"))
        return 2
    print(json.dumps({"passed": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


def _hwp_visual_v2_command(args: argparse.Namespace) -> int:
    """Materialize representative or reviewed-gold-gated HWP visual evidence."""

    from midprojectrag.ingest.hwp_visual_runner import (
        run_hwp_visual_v2_from_manifest,
    )

    try:
        data_dir = args.data_dir.resolve()
        private_root = (
            args.private_root.resolve()
            if args.private_root is not None
            else (data_dir / "private").resolve()
        )
        result = run_hwp_visual_v2_from_manifest(
            manifest_path=args.manifest.resolve(),
            data_dir=data_dir,
            blocks_dir=args.blocks_dir.resolve(),
            selection_path=args.selection.resolve(),
            output_dir=args.output_dir.resolve(),
            private_root=private_root,
            node_executable=args.node_executable.resolve(),
            node_sha256=args.node_sha256,
            helper_path=args.helper.resolve(),
            helper_sha256=args.helper_sha256,
            core_js_path=args.core_js.resolve(),
            core_js_sha256=args.core_js_sha256,
            wasm_path=args.wasm.resolve(),
            wasm_sha256=args.wasm_sha256,
            canvas_module_path=args.canvas_module.resolve(),
            canvas_module_sha256=args.canvas_module_sha256,
            mode=args.mode,
            visual_gold_path=(
                args.visual_gold.resolve() if args.visual_gold is not None else None
            ),
            timeout_seconds=args.timeout_seconds,
            expected_existing_artifact_set_id=args.expected_artifact_set_id,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        _print_failure(_safe_error_code(error, "hwp_visual_v2_failed"))
        return 2
    print(json.dumps({"passed": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


def _strict_visual_config(path: Path, *, kind: str) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise ValueError(f"{kind}_config_invalid") from error
    if not 1 <= len(payload) <= 1024 * 1024:
        raise ValueError(f"{kind}_config_invalid")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{kind}_config_invalid") from error
    if not isinstance(value, dict):
        raise ValueError(f"{kind}_config_invalid")
    return value


def _visual_understanding_command(args: argparse.Namespace) -> int:
    """Run checksum-pinned, offline OCR and optional caption adapters."""

    from midprojectrag.ingest import visual_understanding, visual_understanding_runner
    from midprojectrag.ingest.visual_understanding import (
        CaptionModelConfig,
        PinnedLocalJsonCommandAdapter,
        PpStructureV3Config,
        VisualRetrievalPolicy,
    )
    from midprojectrag.ingest.visual_understanding_runner import (
        run_visual_understanding_batch,
    )

    try:
        ocr_raw = _strict_visual_config(args.ocr_config.resolve(), kind="ocr")
        expected_ocr_fields = {
            "schema_version",
            "pipeline",
            "ocr_version",
            "language",
            "model_version",
            "weights_sha256",
            "runtime",
            "device",
            "text_rec_score_thresh",
            "use_doc_orientation_classify",
            "use_textline_orientation",
            "use_table_recognition",
            "use_ocr_results_with_table_cells",
            "max_text_items",
            "max_table_cells",
            "model_download",
        }
        if (
            set(ocr_raw) != expected_ocr_fields
            or ocr_raw["schema_version"] != "1.0"
            or ocr_raw["pipeline"] != "PP-StructureV3"
            or ocr_raw["ocr_version"] != "PP-OCRv5"
            or ocr_raw["language"] != "korean"
            or ocr_raw["model_download"] != "forbidden"
        ):
            raise ValueError("ocr_config_invalid")
        ocr_config = PpStructureV3Config(
            **{
                key: value
                for key, value in ocr_raw.items()
                if key
                not in {
                    "schema_version",
                    "pipeline",
                    "ocr_version",
                    "language",
                    "model_download",
                }
            }
        )
        sandbox_options = {
            "network_sandbox_backend": args.network_sandbox_backend,
            "network_sandbox_command": args.network_sandbox_command.resolve(),
            "network_sandbox_command_sha256": args.network_sandbox_command_sha256,
        }
        ocr_adapter = PinnedLocalJsonCommandAdapter(
            command=args.ocr_command.resolve(),
            command_sha256=args.ocr_command_sha256,
            model_artifact=args.ocr_model_artifact.resolve(),
            model_artifact_sha256=ocr_config.weights_sha256,
            **sandbox_options,
            arguments=tuple(args.ocr_argument),
            timeout_seconds=args.adapter_timeout_seconds,
        )

        caption_adapter = None
        caption_config = None
        caption_values = (
            args.caption_config,
            args.caption_command,
            args.caption_command_sha256,
            args.caption_model_artifact,
        )
        if any(value is not None for value in caption_values):
            if any(value is None for value in caption_values):
                raise ValueError("caption_config_incomplete")
            caption_raw = _strict_visual_config(
                args.caption_config.resolve(), kind="caption"
            )
            expected_caption_fields = {
                "schema_version",
                "model_name",
                "model_version",
                "weights_sha256",
                "runtime",
                "device",
                "prompt",
                "max_new_tokens",
                "seed",
                "temperature",
                "do_sample",
                "model_download",
            }
            if (
                set(caption_raw) != expected_caption_fields
                or caption_raw["schema_version"] != "1.0"
                or caption_raw["model_download"] != "forbidden"
            ):
                raise ValueError("caption_config_invalid")
            caption_config = CaptionModelConfig(
                **{
                    key: value
                    for key, value in caption_raw.items()
                    if key not in {"schema_version", "model_download"}
                }
            )
            caption_adapter = PinnedLocalJsonCommandAdapter(
                command=args.caption_command.resolve(),
                command_sha256=args.caption_command_sha256,
                model_artifact=args.caption_model_artifact.resolve(),
                model_artifact_sha256=caption_config.weights_sha256,
                **sandbox_options,
                arguments=tuple(args.caption_argument),
                timeout_seconds=args.adapter_timeout_seconds,
            )
        policy = VisualRetrievalPolicy(
            ocr_weight=args.ocr_weight,
            layout_weight=args.layout_weight,
            caption_weight=args.caption_weight,
            caption_per_query=args.caption_per_query,
            caption_per_document=args.caption_per_document,
        )
        adapter_code_sha256 = sha256_text(
            canonical_json(
                {
                    "understanding": sha256_file(
                        Path(visual_understanding.__file__).resolve()
                    ),
                    "runner": sha256_file(
                        Path(visual_understanding_runner.__file__).resolve()
                    ),
                }
            )
        )
        result = run_visual_understanding_batch(
            private_root=args.private_root.resolve(),
            occurrences_path=args.occurrences.resolve(),
            output_root=args.output_root.resolve(),
            adapter_code_sha256=adapter_code_sha256,
            ocr_adapter=ocr_adapter,
            ocr_config=ocr_config,
            policy=policy,
            caption_adapter=caption_adapter,
            caption_config=caption_config,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        _print_failure(_safe_error_code(error, "visual_understanding_failed"))
        return 2
    print(json.dumps({"passed": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


def _chunk_command(args: argparse.Namespace) -> int:
    from midprojectrag.indexing.chunking import (
        PageChunkConfig,
        build_page_chunks_from_manifest,
        chunk_artifact_sha256,
    )

    data_dir = args.data_dir.resolve()
    try:
        manifest = require_within(args.manifest.resolve(), data_dir, "manifest_path_outside_data_dir")
        blocks_dir = require_within(args.blocks_dir.resolve(), data_dir, "blocks_path_outside_data_dir")
        output = require_within(args.output.resolve(), data_dir, "chunk_output_outside_data_dir")
        chunks = build_page_chunks_from_manifest(
            manifest,
            blocks_dir,
            PageChunkConfig(max_chars=args.max_chars),
        )
        write_jsonl(output, chunks)
        artifact_sha256 = chunk_artifact_sha256(chunks)
        metadata_path = output.with_name(f"{output.name}.metadata.json")
        write_json(
            metadata_path,
            {
                "schema_version": "1.0",
                "source_manifest_sha256": sha256_file(manifest),
                "chunk_artifact_sha256": artifact_sha256,
                "config_sha256": chunks[0]["config_sha256"],
                "documents": len({chunk["doc_id"] for chunk in chunks}),
                "chunks": len(chunks),
            },
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        _print_failure(_safe_error_code(error, "chunk_build_failed"))
        return 5
    summary = {
        "passed": True,
        "documents": len({chunk["doc_id"] for chunk in chunks}),
        "chunks": len(chunks),
        "auxiliary_chunks": sum(chunk["retrieval_role"] != "primary" for chunk in chunks),
        "artifact_sha256": artifact_sha256,
        "config_sha256": chunks[0]["config_sha256"],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _table_chunk_command(args: argparse.Namespace) -> int:
    from midprojectrag.indexing.chunking import (
        TableChunkConfig,
        build_table_chunks_from_manifest,
        chunk_artifact_sha256,
    )
    from midprojectrag.stacks.api import TiktokenCounter

    data_dir = args.data_dir.resolve()
    try:
        manifest = require_within(
            args.manifest.resolve(), data_dir, "manifest_path_outside_data_dir"
        )
        blocks_dir = require_within(
            args.blocks_dir.resolve(), data_dir, "blocks_path_outside_data_dir"
        )
        output = require_within(
            args.output.resolve(), data_dir, "chunk_output_outside_data_dir"
        )
        tokenizer_cache_dir = require_within(
            args.tokenizer_cache_dir.resolve(),
            data_dir,
            "tokenizer_cache_path_outside_data_dir",
        )
        layout_path = None
        layout_records = None
        if args.layout_overlay is not None:
            layout_path = require_within(
                args.layout_overlay.resolve(),
                data_dir,
                "table_layout_path_outside_data_dir",
            )
            layout_records = read_jsonl(layout_path)
        config = TableChunkConfig(
            max_rows=args.max_rows,
            max_chars=args.max_chars,
            max_tokens=args.max_tokens,
            summary_chars=args.summary_chars,
        )
        chunks = build_table_chunks_from_manifest(
            manifest,
            blocks_dir,
            config=config,
            counter=TiktokenCounter(
                "text-embedding-3-small", cache_dir=tokenizer_cache_dir
            ),
            layout_records=layout_records,
        )
        write_jsonl(output, chunks)
        artifact_sha256 = chunk_artifact_sha256(chunks)
        manifest_rows = read_jsonl(manifest)
        eligible_documents = len(
            {
                row.get("doc_id")
                for row in manifest_rows
                if row.get("status") == "ok" and row.get("index_eligible") is True
            }
        )
        metadata_path = output.with_name(f"{output.name}.metadata.json")
        write_json(
            metadata_path,
            {
                "schema_version": "1.2" if layout_path is not None else "1.1",
                "source_manifest_sha256": sha256_file(manifest),
                "chunk_artifact_sha256": artifact_sha256,
                "config_sha256": config.config_sha256,
                "documents": len({chunk["doc_id"] for chunk in chunks}),
                "eligible_documents": eligible_documents,
                "chunks": len(chunks),
                "retrieval_role": "structured_auxiliary",
                "chunker_id": config.chunker_id,
                "coverage_policy": "eligible_subset",
                "tokenizer_id": config.tokenizer_id,
                **(
                    {"layout_overlay_sha256": sha256_file(layout_path)}
                    if layout_path is not None
                    else {}
                ),
            },
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        _print_failure(_safe_error_code(error, "table_chunk_build_failed"))
        return 5
    summary = {
        "passed": True,
        "documents": len({chunk["doc_id"] for chunk in chunks}),
        "eligible_documents": eligible_documents,
        "chunks": len(chunks),
        "artifact_sha256": artifact_sha256,
        "config_sha256": config.config_sha256,
        "page_linked_chunks": sum(chunk["page_start"] is not None for chunk in chunks),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _table_layout_command(args: argparse.Namespace) -> int:
    from midprojectrag.ingest.rhwp_adapter import (
        is_verified_rhwp_identity,
        resolve_rhwp_command,
        rhwp_version,
        verified_rhwp_sha256,
    )
    from midprojectrag.ingest.table_layout import (
        build_table_layout_overlay,
        load_rhwp_layout_inputs,
    )

    data_dir = args.data_dir.resolve()
    try:
        manifest_path = require_within(
            args.manifest.resolve(), data_dir, "manifest_path_outside_data_dir"
        )
        blocks_dir = require_within(
            args.blocks_dir.resolve(), data_dir, "blocks_path_outside_data_dir"
        )
        output = require_within(
            args.output.resolve(), data_dir, "table_layout_output_outside_data_dir"
        )
        command = resolve_rhwp_command()
        if command is None:
            raise ValueError("verified_rhwp_required")
        identity = rhwp_version(command)
        if not is_verified_rhwp_identity(identity):
            raise ValueError("verified_rhwp_required")
        binary_sha256 = verified_rhwp_sha256(identity)
        if binary_sha256 is None:
            raise ValueError("verified_rhwp_required")

        manifest_rows = read_jsonl(manifest_path)
        seen_doc_ids: set[str] = set()
        records: list[dict[str, Any]] = []
        hwp_documents = 0
        for row in sorted(manifest_rows, key=lambda value: str(value.get("doc_id", ""))):
            doc_id = row.get("doc_id")
            if not isinstance(doc_id, str) or not doc_id or doc_id in seen_doc_ids:
                raise ValueError("invalid_or_duplicate_manifest_doc_id")
            seen_doc_ids.add(doc_id)
            if row.get("status") != "ok" or row.get("index_eligible") is not True:
                raise ValueError("manifest_document_not_index_eligible")
            if row.get("extension") not in {".hwp", ".hwpx"}:
                continue
            hwp_documents += 1
            source_path = require_within(
                data_dir / str(row.get("source_relpath", "")),
                data_dir,
                "layout_source_path_outside_data_dir",
            )
            source_sha256 = require_sha256(
                row.get("sha256"), "invalid_layout_source_hash"
            )
            if not source_path.is_file() or sha256_file(source_path) != source_sha256:
                raise ValueError("layout_source_hash_mismatch")
            block_path = require_within(
                blocks_dir / f"{doc_id}.jsonl",
                blocks_dir,
                "layout_block_path_outside_blocks_dir",
            )
            blocks = read_jsonl(block_path)
            dump_pages, render_trees = load_rhwp_layout_inputs(
                command,
                source_path,
                timeout_seconds=args.timeout_seconds,
            )
            records.extend(
                build_table_layout_overlay(
                    doc_id=doc_id,
                    blocks=blocks,
                    dump_pages=dump_pages,
                    render_trees=render_trees,
                )
            )
        if hwp_documents < 1 or not records:
            raise ValueError("no_table_layout_records")
        records.sort(key=lambda value: (value["doc_id"], value["block_id"]))
        write_jsonl(output, records)
        artifact_sha256 = sha256_file(output)
        status_counts: dict[str, int] = {}
        for record in records:
            status = record["status"]
            status_counts[status] = status_counts.get(status, 0) + 1
        write_json(
            output.with_name(f"{output.name}.metadata.json"),
            {
                "schema_version": "1.0",
                "source_manifest_sha256": sha256_file(manifest_path),
                "artifact_sha256": artifact_sha256,
                "method": "render-tree-key-v1",
                "coordinate_space": "rhwp_css_px_96dpi",
                "rhwp_binary_sha256": binary_sha256,
                "documents": hwp_documents,
                "tables": len(records),
                "status_counts": status_counts,
            },
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        _print_failure(_safe_error_code(error, "table_layout_build_failed"))
        return 5
    summary = {
        "passed": True,
        "documents": hwp_documents,
        "tables": len(records),
        "status_counts": status_counts,
        "page_linked": sum(record["page_start"] is not None for record in records),
        "bbox_invalid": sum(
            not page_bbox["bbox_valid"]
            for record in records
            for page_bbox in record["page_bboxes"]
        ),
        "artifact_sha256": artifact_sha256,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _hwp_visual_corpus_command(args: argparse.Namespace) -> int:
    from midprojectrag.ingest.rhwp_adapter import (
        is_verified_rhwp_identity,
        resolve_rhwp_command,
        rhwp_version,
        verified_rhwp_sha256,
    )
    from midprojectrag.ingest.visual_corpus import (
        VISUAL_CORPUS_CONFIG_SHA256,
        load_hwp_visual_documents,
        run_hwp_visual_corpus,
    )

    data_dir = args.data_dir.resolve()
    try:
        private_root = require_within(
            (args.private_root or data_dir / "private").resolve(),
            data_dir,
            "visual_corpus_private_root_outside_data_dir",
        )
        manifest_path = require_within(
            args.manifest.resolve(), data_dir, "visual_corpus_manifest_outside_data_dir"
        )
        blocks_dir = require_within(
            args.blocks_dir.resolve(), data_dir, "visual_corpus_blocks_outside_data_dir"
        )
        layout_path = require_within(
            args.layout_overlay.resolve(),
            data_dir,
            "visual_corpus_layout_outside_data_dir",
        )
        selection_path = require_within(
            args.selection.resolve(),
            data_dir,
            "visual_corpus_selection_outside_data_dir",
        )
        try:
            selection = json.loads(selection_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise ValueError("visual_corpus_selection_invalid") from None
        if not isinstance(selection, dict) or not isinstance(
            selection.get("documents"), list
        ):
            raise ValueError("visual_corpus_selection_invalid")
        sample_doc_ids = [row.get("doc_id") for row in selection["documents"] if isinstance(row, dict)]
        if (
            len(sample_doc_ids) != 5
            or any(not isinstance(doc_id, str) for doc_id in sample_doc_ids)
            or len(sample_doc_ids) != len(set(sample_doc_ids))
        ):
            raise ValueError("visual_corpus_selection_invalid")
        doc_ids = sample_doc_ids if args.mode == "sample" else None
        documents, identity = load_hwp_visual_documents(
            data_dir=data_dir,
            manifest_path=manifest_path,
            blocks_dir=blocks_dir,
            layout_path=layout_path,
            doc_ids=doc_ids,
            expected_hwp=args.expected_hwp,
        )
        command = resolve_rhwp_command()
        if command is None:
            raise ValueError("verified_rhwp_required")
        rhwp_identity = rhwp_version(command)
        if not is_verified_rhwp_identity(rhwp_identity):
            raise ValueError("verified_rhwp_required")
        rhwp_sha256 = verified_rhwp_sha256(rhwp_identity)
        if rhwp_sha256 is None:
            raise ValueError("verified_rhwp_required")
        selection_sha256 = sha256_file(selection_path)
        run_id = "run_" + sha256_text(
            canonical_json(
                {
                    "config_sha256": VISUAL_CORPUS_CONFIG_SHA256,
                    "doc_ids": sorted(document["doc_id"] for document in documents),
                    "layout_sha256": identity["table_layout_artifact_sha256"],
                    "manifest_sha256": identity["source_manifest_sha256"],
                    "mode": args.mode,
                    "rhwp_sha256": rhwp_sha256,
                    "selection_sha256": selection_sha256,
                }
            )
        )[:24]
        output_root = require_within(
            (args.output_root or private_root / "visual-v1").resolve(),
            private_root,
            "visual_corpus_output_outside_private_root",
        )
        asset_root = require_within(
            (args.asset_root or private_root / "hwp-assets-v1").resolve(),
            private_root,
            "visual_corpus_asset_outside_private_root",
        )
        default_report = output_root / (
            "sample-run-v1.metadata.json"
            if args.mode == "sample"
            else "corpus-run-v1.metadata.json"
        )
        report_output = require_within(
            (args.report_output or default_report).resolve(),
            private_root,
            "visual_corpus_report_outside_private_root",
        )
        report = run_hwp_visual_corpus(
            command=command,
            documents=documents,
            output_root=output_root,
            asset_root=asset_root,
            private_root=private_root,
            config_sha256=VISUAL_CORPUS_CONFIG_SHA256,
            expected_rhwp_sha256=rhwp_sha256,
            continue_on_error=args.continue_on_error,
            run_id=run_id,
            mode=args.mode,
            selection_sha256=selection_sha256,
            source_manifest_sha256=identity["source_manifest_sha256"],
            table_layout_artifact_sha256=identity[
                "table_layout_artifact_sha256"
            ],
            report_output=report_output,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        _print_failure(_safe_error_code(error, "visual_corpus_failed"))
        return 5
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "mode": report["mode"],
                "run_id": report["run_id"],
                "totals": report["totals"],
                "artifact_set_digest": report["artifact_set_digest"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 5


def _hwp_visual_select_command(args: argparse.Namespace) -> int:
    from midprojectrag.ingest.visual_corpus import (
        build_hwp_visual_structural_stats,
        load_hwp_visual_documents,
        select_hwp_visual_samples,
    )

    data_dir = args.data_dir.resolve()
    try:
        documents, identity = load_hwp_visual_documents(
            data_dir=data_dir,
            manifest_path=args.manifest.resolve(),
            blocks_dir=args.blocks_dir.resolve(),
            layout_path=args.layout_overlay.resolve(),
            expected_hwp=args.expected_hwp,
        )
        private_root = require_within(
            (args.private_root or data_dir / "private").resolve(),
            data_dir,
            "visual_corpus_private_root_outside_data_dir",
        )
        existing_visual_root = require_within(
            (args.existing_visual_root or private_root / "visual-v1").resolve(),
            private_root,
            "visual_corpus_output_outside_private_root",
        )
        output = require_within(
            args.output.resolve(),
            private_root,
            "visual_corpus_selection_outside_private_root",
        )
        structural_stats = build_hwp_visual_structural_stats(
            documents, existing_visual_root=existing_visual_root
        )
        selection = select_hwp_visual_samples(structural_stats)
        selection.update(
            {
                "source_manifest_sha256": identity["source_manifest_sha256"],
                "table_layout_artifact_sha256": identity[
                    "table_layout_artifact_sha256"
                ],
                "structural_stats_sha256": sha256_text(
                    canonical_json(structural_stats)
                ),
            }
        )
        write_json(output, selection)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        _print_failure(_safe_error_code(error, "visual_sample_selection_failed"))
        return 5
    print(
        json.dumps(
            {
                "passed": True,
                "documents": len(selection["documents"]),
                "doc_ids": [row["doc_id"] for row in selection["documents"]],
                "selection_policy_sha256": selection["selection_policy_sha256"],
                "selection_artifact_sha256": sha256_file(output),
            },
            sort_keys=True,
        )
    )
    return 0


def _visual_table_corpus_command(args: argparse.Namespace) -> int:
    from midprojectrag.indexing.visual_table_context import (
        materialize_visual_table_corpus,
    )

    data_dir = args.data_dir.resolve()
    try:
        private_root = require_within(
            (args.private_root or data_dir / "private").resolve(),
            data_dir,
            "visual_corpus_private_root_outside_data_dir",
        )
        corpus_metadata = require_within(
            args.corpus_metadata.resolve(),
            private_root,
            "visual_corpus_path_outside_private_root",
        )
        try:
            rollout = json.loads(corpus_metadata.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise ValueError("visual_corpus_metadata_invalid") from None
        if not isinstance(rollout, dict) or rollout.get("passed") is not True:
            raise ValueError("visual_corpus_metadata_invalid")
        document_rows = rollout.get("documents")
        if not isinstance(document_rows, list) or not document_rows:
            raise ValueError("visual_corpus_metadata_invalid")
        doc_ids = [
            row.get("doc_id")
            for row in document_rows
            if isinstance(row, dict)
            and row.get("terminal_state") in {"materialized", "reused"}
        ]
        if len(doc_ids) != len(document_rows) or len(doc_ids) != len(set(doc_ids)):
            raise ValueError("visual_corpus_metadata_invalid")
        overlay_root = require_within(
            (args.overlay_root or private_root / "visual-v1").resolve(),
            private_root,
            "visual_corpus_path_outside_private_root",
        )
        overlay_paths = [
            overlay_root / str(doc_id) / "table-visual-v1.jsonl"
            for doc_id in sorted(doc_ids)
        ]
        metadata = materialize_visual_table_corpus(
            source_chunks_path=args.source_chunks.resolve(),
            overlay_paths=overlay_paths,
            corpus_metadata_path=corpus_metadata,
            output_path=args.output.resolve(),
            metadata_output=(
                args.metadata_output
                or args.output.with_name(f"{args.output.name}.metadata.json")
            ).resolve(),
            private_root=private_root,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        _print_failure(_safe_error_code(error, "visual_table_corpus_failed"))
        return 5
    print(json.dumps({"passed": True, **metadata}, ensure_ascii=False, sort_keys=True))
    return 0


def _require_external_egress_confirmation(args: argparse.Namespace) -> bool:
    if args.approve_external_corpus_egress:
        return True
    _print_failure("external_corpus_egress_not_approved")
    return False


def _tokenizer_cache_command(args: argparse.Namespace) -> int:
    if not args.approve_static_tokenizer_download:
        _print_failure("static_tokenizer_download_not_approved")
        return 6
    from midprojectrag.stacks.api import warm_tiktoken_cache

    data_dir = args.data_dir.resolve()
    try:
        if not data_dir.is_dir():
            raise ValueError("data_dir_missing")
        cache_dir = require_within(
            (args.cache_dir or data_dir / "private" / "tiktoken-cache").resolve(),
            data_dir,
            "tokenizer_cache_path_outside_data_dir",
        )
        assets = warm_tiktoken_cache(cache_dir)
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        _print_failure(_safe_error_code(error, "tokenizer_cache_failed"))
        return 6
    except Exception:
        _print_failure("tokenizer_cache_failed")
        return 6
    print(
        json.dumps(
            {"passed": True, "assets": len(assets), "asset_sha256": assets},
            sort_keys=True,
        )
    )
    return 0


def _load_verified_index_inputs(
    args: argparse.Namespace,
    data_dir: Path,
    *,
    stack_id: str,
) -> tuple[list[dict[str, object]], Path, Path]:
    from midprojectrag.indexing.chunking import chunk_artifact_sha256

    chunks_path = require_within(args.chunks.resolve(), data_dir, "chunks_path_outside_data_dir")
    output_dir = _require_stack_artifact_path(
        args.output_dir.resolve(),
        data_dir,
        stack_id=stack_id,
        artifact_kind="indexes",
        error_code=f"{stack_id}_index_output_outside_stack_root",
    )
    cache_dir = _require_stack_artifact_path(
        args.cache_dir.resolve(),
        data_dir,
        stack_id=stack_id,
        artifact_kind="caches",
        error_code=f"{stack_id}_cache_path_outside_stack_root",
    )
    if args.manifest is None:
        raise ValueError("manifest_path_required")
    manifest_path = require_within(
        args.manifest.resolve(), data_dir, "manifest_path_outside_data_dir"
    )
    if sha256_file(manifest_path) != args.manifest_sha256:
        raise ValueError("corpus_manifest_hash_mismatch")
    chunks = read_jsonl(chunks_path)
    chunk_metadata_path = require_within(
        (args.chunk_metadata or chunks_path.with_name(f"{chunks_path.name}.metadata.json")).resolve(),
        data_dir,
        "chunk_metadata_path_outside_data_dir",
    )
    with chunk_metadata_path.open("r", encoding="utf-8") as source:
        chunk_metadata = json.load(source)
    page_chunk_metadata_fields = {
        "schema_version",
        "source_manifest_sha256",
        "chunk_artifact_sha256",
        "config_sha256",
        "documents",
        "chunks",
    }
    table_chunk_metadata_fields = page_chunk_metadata_fields | {
        "eligible_documents",
        "retrieval_role",
        "chunker_id",
        "coverage_policy",
        "tokenizer_id",
    }
    linked_table_chunk_metadata_fields = table_chunk_metadata_fields | {
        "layout_overlay_sha256"
    }
    visual_table_chunk_metadata_fields = {
        "schema_version",
        "method",
        "chunker_id",
        "retrieval_role",
        "source_manifest_sha256",
        "source_chunk_artifact_sha256",
        "overlay_artifact_sha256",
        "corpus_metadata_sha256",
        "chunk_artifact_sha256",
        "config_sha256",
        "documents",
        "source_chunks",
        "chunks",
        "overlay_records",
        "context_counts",
        "table_status_counts",
    }
    if not isinstance(chunk_metadata, dict):
        raise ValueError("invalid_chunk_metadata")
    metadata_schema_version = chunk_metadata.get("schema_version")
    metadata_contract: str
    if metadata_schema_version == "1.0":
        if set(chunk_metadata) != page_chunk_metadata_fields:
            raise ValueError("invalid_chunk_metadata")
        metadata_contract = "page"
    elif (
        metadata_schema_version == "1.2"
        and chunk_metadata.get("chunker_id") == "table-md-visual-context-v2"
    ):
        context_counts = chunk_metadata.get("context_counts")
        table_status_counts = chunk_metadata.get("table_status_counts")
        if (
            set(chunk_metadata) != visual_table_chunk_metadata_fields
            or chunk_metadata.get("method")
            != "exact-block-prior-context-row-scoped-schedule-v1"
            or chunk_metadata.get("retrieval_role") != "structured_auxiliary"
            or any(
                not isinstance(chunk_metadata.get(field), int)
                or isinstance(chunk_metadata.get(field), bool)
                or chunk_metadata.get(field, 0) < 1
                for field in (
                    "documents",
                    "source_chunks",
                    "chunks",
                    "overlay_records",
                )
            )
            or chunk_metadata.get("source_chunks") != chunk_metadata.get("chunks")
            or not isinstance(context_counts, dict)
            or set(context_counts)
            != {"chunks_with_prior_context", "chunks_with_schedule_context"}
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in context_counts.values()
            )
            or any(
                value > chunk_metadata["chunks"] for value in context_counts.values()
            )
            or not isinstance(table_status_counts, dict)
            or not table_status_counts
            or not set(table_status_counts).issubset(
                {
                    "layout_missing",
                    "layout_unresolved",
                    "render_occurrence_unresolved",
                    "verified_render",
                }
            )
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 1
                for value in table_status_counts.values()
            )
            or sum(table_status_counts.values())
            != chunk_metadata["overlay_records"]
        ):
            raise ValueError("invalid_chunk_metadata")
        for field in (
            "source_chunk_artifact_sha256",
            "overlay_artifact_sha256",
            "corpus_metadata_sha256",
        ):
            require_sha256(chunk_metadata.get(field), "invalid_chunk_metadata")
        metadata_contract = "visual_table"
    elif metadata_schema_version in {"1.1", "1.2"}:
        expected_fields = (
            linked_table_chunk_metadata_fields
            if metadata_schema_version == "1.2"
            else table_chunk_metadata_fields
        )
        if (
            set(chunk_metadata) != expected_fields
            or chunk_metadata.get("retrieval_role") != "structured_auxiliary"
            or chunk_metadata.get("chunker_id") != "table-md-rowgroup-v1"
            or chunk_metadata.get("coverage_policy") != "eligible_subset"
            or chunk_metadata.get("tokenizer_id") != "cl100k_base-pinned"
        ):
            raise ValueError("invalid_chunk_metadata")
        if metadata_schema_version == "1.2":
            require_sha256(
                chunk_metadata.get("layout_overlay_sha256"),
                "invalid_chunk_metadata",
            )
        metadata_contract = "table"
    else:
        raise ValueError("invalid_chunk_metadata")
    if chunk_metadata["source_manifest_sha256"] != args.manifest_sha256:
        raise ValueError("chunk_manifest_hash_mismatch")
    if (
        chunk_metadata["chunk_artifact_sha256"] != sha256_file(chunks_path)
        or chunk_metadata["chunk_artifact_sha256"]
        != chunk_artifact_sha256(chunks)
    ):
        raise ValueError("chunk_artifact_hash_mismatch")
    if chunk_metadata["chunks"] != len(chunks):
        raise ValueError("chunk_count_mismatch")
    if not chunks or {chunk.get("config_sha256") for chunk in chunks} != {
        chunk_metadata["config_sha256"]
    }:
        raise ValueError("chunk_config_hash_mismatch")
    manifest_rows = read_jsonl(manifest_path)
    eligible_doc_ids = {
        row.get("doc_id")
        for row in manifest_rows
        if row.get("status") == "ok" and row.get("index_eligible") is True
    }
    eligible_hwp_doc_ids = {
        row.get("doc_id")
        for row in manifest_rows
        if row.get("status") == "ok"
        and row.get("index_eligible") is True
        and row.get("extension") == ".hwp"
    }
    chunk_doc_ids = {chunk.get("doc_id") for chunk in chunks}
    if metadata_contract == "page":
        if chunk_doc_ids != eligible_doc_ids:
            raise ValueError("chunk_manifest_document_mismatch")
    else:
        expected_chunker_id = (
            "table-md-visual-context-v2"
            if metadata_contract == "visual_table"
            else "table-md-rowgroup-v1"
        )
        if (
            not chunk_doc_ids
            or not chunk_doc_ids.issubset(eligible_doc_ids)
            or (
                metadata_contract == "visual_table"
                and chunk_doc_ids != eligible_hwp_doc_ids
            )
            or (
                metadata_contract == "table"
                and chunk_metadata["eligible_documents"] != len(eligible_doc_ids)
            )
            or any(
                chunk.get("retrieval_role") != "structured_auxiliary"
                or chunk.get("chunker_id") != expected_chunker_id
                for chunk in chunks
            )
        ):
            raise ValueError("chunk_manifest_document_mismatch")
    if chunk_metadata["documents"] != len(chunk_doc_ids):
        raise ValueError("chunk_manifest_document_mismatch")
    return chunks, output_dir, cache_dir


def _index_command(args: argparse.Namespace) -> int:
    if not _require_external_egress_confirmation(args):
        return 6
    from midprojectrag.indexing.budget import BudgetLedger
    from midprojectrag.indexing.embeddings import EmbeddingCache, embed_chunks
    from midprojectrag.indexing.exact_index import ExactDenseIndex
    from midprojectrag.indexing.chunking import chunk_artifact_sha256
    from midprojectrag.stacks.api import (
        OpenAIEmbeddingProvider,
        TiktokenCounter,
        api_config_sha256,
        build_api_index_config,
    )

    data_dir = args.data_dir.resolve()
    try:
        chunks, output_dir, cache_dir = _load_verified_index_inputs(
            args,
            data_dir,
            stack_id="api",
        )
        tokenizer_cache_dir = require_within(
            (args.tokenizer_cache_dir or data_dir / "private" / "tiktoken-cache").resolve(),
            data_dir,
            "tokenizer_cache_path_outside_data_dir",
        )
        budget_path = require_within(args.budget_ledger.resolve(), data_dir, "budget_path_outside_data_dir")
        provider = OpenAIEmbeddingProvider(
            model=args.model,
            dimensions=args.dimensions,
            api_profile=args.api_profile,
        )
        index_config = build_api_index_config(
            api_profile=args.api_profile,
            corpus_manifest_sha256=args.manifest_sha256,
            chunk_artifact_sha256=chunk_artifact_sha256(chunks),
            chunk_config_sha256=chunks[0]["config_sha256"],
            embedding_model=args.model,
            embedding_dimensions=provider.dimensions,
            index_engine=args.engine,
            batch_size=args.batch_size,
        )
        index_config_hash = api_config_sha256(index_config)
        result = embed_chunks(
            chunks,
            provider=provider,
            counter=TiktokenCounter(args.model, cache_dir=tokenizer_cache_dir),
            cache=EmbeddingCache(cache_dir),
            corpus_manifest_sha256=args.manifest_sha256,
            budget=BudgetLedger(budget_path, limit_usd=args.max_api_budget_usd),
            batch_size=args.batch_size,
            batch_interval_seconds=args.batch_interval_seconds,
        )
        index = ExactDenseIndex(chunks, result.vectors, engine=args.engine)
        metadata = index.save(
            output_dir,
            corpus_manifest_sha256=args.manifest_sha256,
            embedding_model=args.model,
            api_profile=args.api_profile,
            index_config_sha256=index_config_hash,
        )
        write_json(output_dir / "index-config.json", index_config)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        _print_failure(_safe_error_code(error, "index_build_failed"))
        return 6
    except Exception as error:
        _print_failure(_safe_provider_error_code(error, "index_build_failed"))
        return 6
    summary = {
        "passed": True,
        "engine": metadata["engine"],
        "chunks": metadata["count"],
        "dimensions": metadata["dimensions"],
        "api_profile": args.api_profile,
        "embedding_model": args.model,
        "index_config_sha256": index_config_hash,
        "cache_hits": result.cache_hits,
        "cache_misses": result.cache_misses,
        "embedding_tokens": result.input_tokens,
        "cost_usd": float(result.cost_usd),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _migrate_index_subset_command(args: argparse.Namespace) -> int:
    """Publish a local API-index subset without contacting any provider."""

    from midprojectrag.indexing.subset_migration import migrate_api_exact_index_subset

    try:
        source_data_dir = args.source_data_dir.resolve()
        target_data_dir = args.target_data_dir.resolve()
        if not source_data_dir.is_dir() or not target_data_dir.is_dir():
            raise ValueError("migration_data_dir_missing")
        source_chunks = require_within(
            args.source_chunks.resolve(),
            source_data_dir,
            "source_chunks_outside_source_data_dir",
        )
        source_index_dir = _require_stack_artifact_path(
            args.source_index_dir.resolve(),
            source_data_dir,
            stack_id="api",
            artifact_kind="indexes",
            error_code="source_index_outside_api_stack_root",
        )
        target_chunks = require_within(
            args.target_chunks.resolve(),
            target_data_dir,
            "target_chunks_outside_target_data_dir",
        )
        target_manifest = require_within(
            args.target_manifest.resolve(),
            target_data_dir,
            "target_manifest_outside_target_data_dir",
        )
        target_chunk_metadata = require_within(
            (
                args.target_chunk_metadata
                or target_chunks.with_name(f"{target_chunks.name}.metadata.json")
            ).resolve(),
            target_data_dir,
            "target_chunk_metadata_outside_target_data_dir",
        )
        output_dir = _require_stack_artifact_path(
            args.output_dir.resolve(),
            target_data_dir,
            stack_id="api",
            artifact_kind="indexes",
            error_code="target_index_outside_api_stack_root",
        )
        if (
            not source_chunks.is_file()
            or not source_index_dir.is_dir()
            or not target_chunks.is_file()
            or not target_manifest.is_file()
            or not target_chunk_metadata.is_file()
        ):
            raise ValueError("migration_input_missing")
        result = migrate_api_exact_index_subset(
            source_chunks_path=source_chunks,
            source_index_dir=source_index_dir,
            target_chunks_path=target_chunks,
            target_chunk_metadata_path=target_chunk_metadata,
            target_manifest_path=target_manifest,
            target_manifest_sha256=args.target_manifest_sha256,
            output_dir=output_dir,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        _print_failure(_safe_error_code(error, "index_subset_migration_failed"))
        return 6
    summary = {
        "passed": True,
        "network_access": False,
        "source_chunks": result.provenance["source"]["count"],
        "target_chunks": result.metadata["count"],
        "removed_chunks": result.provenance["removed_count"],
        "engine": result.metadata["engine"],
        "dimensions": result.metadata["dimensions"],
        "api_profile": result.metadata["api_profile"],
        "embedding_model": result.metadata["embedding_model"],
        "index_config_sha256": result.metadata["index_config_sha256"],
        "migration_provenance_sha256": result.provenance_sha256,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _query_command(args: argparse.Namespace) -> int:
    if not _require_external_egress_confirmation(args):
        return 7
    observability = args.observability.strip().lower()
    if observability not in {"disabled", "memory", "langfuse"}:
        _print_failure("invalid_observability_backend")
        return 7
    if observability == "langfuse" and not args.approve_langfuse_metadata_egress:
        _print_failure("langfuse_metadata_egress_not_approved")
        return 7
    from midprojectrag.answering.pipeline import RagPipeline
    from midprojectrag.indexing.budget import BudgetLedger
    from midprojectrag.indexing.embeddings import EmbeddingCache
    from midprojectrag.indexing.exact_index import ExactDenseIndex
    from midprojectrag.observability import create_observer
    from midprojectrag.stacks.api import (
        OpenAIEmbeddingProvider,
        OpenAIGenerator,
        TiktokenCounter,
        build_api_run_record,
    )

    data_dir = args.data_dir.resolve()
    observer = create_observer(observability)
    try:
        chunks_path = require_within(args.chunks.resolve(), data_dir, "chunks_path_outside_data_dir")
        index_dir = _require_stack_artifact_path(
            args.index_dir.resolve(),
            data_dir,
            stack_id="api",
            artifact_kind="indexes",
            error_code="api_index_path_outside_stack_root",
        )
        request_path = require_within(args.request.resolve(), data_dir, "request_path_outside_data_dir")
        output_path = _require_stack_artifact_path(
            args.output.resolve(),
            data_dir,
            stack_id="api",
            artifact_kind="outputs",
            error_code="api_query_output_outside_stack_root",
        )
        cache_dir = _require_stack_artifact_path(
            args.cache_dir.resolve(),
            data_dir,
            stack_id="api",
            artifact_kind="caches",
            error_code="api_cache_path_outside_stack_root",
        )
        tokenizer_cache_dir = require_within(
            (args.tokenizer_cache_dir or data_dir / "private" / "tiktoken-cache").resolve(),
            data_dir,
            "tokenizer_cache_path_outside_data_dir",
        )
        budget_path = require_within(args.budget_ledger.resolve(), data_dir, "budget_path_outside_data_dir")
        if (args.run_context is None) != (args.run_record_output is None):
            raise ValueError("run_record_arguments_incomplete")
        run_context_path = (
            require_within(args.run_context.resolve(), data_dir, "run_context_path_outside_data_dir")
            if args.run_context is not None
            else None
        )
        run_record_output = (
            _require_stack_artifact_path(
                args.run_record_output.resolve(),
                data_dir,
                stack_id="api",
                artifact_kind="outputs",
                error_code="api_run_record_outside_stack_root",
            )
            if args.run_record_output is not None
            else None
        )
        chunks = read_jsonl(chunks_path)
        with (index_dir / "metadata.json").open("r", encoding="utf-8") as source:
            index_metadata = json.load(source)
        with (index_dir / "index-config.json").open("r", encoding="utf-8") as source:
            index_config = json.load(source)
        from midprojectrag.stacks.api import api_config_sha256

        index_config_hash = api_config_sha256(index_config)
        if (
            index_metadata.get("api_profile") != args.api_profile
            or index_metadata.get("index_config_sha256") != index_config_hash
            or index_config.get("api_profile") != args.api_profile
            or index_config.get("embedding_model") != index_metadata.get("embedding_model")
            or index_config.get("embedding_dimensions") != index_metadata.get("dimensions")
        ):
            raise ValueError("index_expected_config_mismatch")
        with request_path.open("r", encoding="utf-8") as source:
            request = json.load(source)
        if run_context_path is not None:
            with run_context_path.open("r", encoding="utf-8") as source:
                run_context = json.load(source)
        else:
            run_context = None
        index = ExactDenseIndex.load(
            index_dir,
            chunks,
            expected_embedding_model=index_metadata["embedding_model"],
            expected_dimensions=index_metadata["dimensions"],
            expected_api_profile=args.api_profile,
            expected_index_config_sha256=index_config_hash,
        )
        budget = BudgetLedger(budget_path, limit_usd=args.max_api_budget_usd)
        embedding_provider = OpenAIEmbeddingProvider(
            model=index_metadata["embedding_model"],
            dimensions=index_metadata["dimensions"],
            api_profile=args.api_profile,
        )
        request_options = request.get("options")
        request_max_citations = (
            request_options.get("max_citations")
            if isinstance(request_options, dict)
            else None
        )
        generator = OpenAIGenerator(
            model=args.generator_model,
            max_output_tokens=args.max_output_tokens,
            max_citations=request_max_citations,
        )
        pipeline = RagPipeline(
            index=index,
            embedding_provider=embedding_provider,
            embedding_counter=TiktokenCounter(
                index_metadata["embedding_model"], cache_dir=tokenizer_cache_dir
            ),
            query_cache=EmbeddingCache(cache_dir),
            generator=generator,
            generation_counter=TiktokenCounter(
                args.generator_model, cache_dir=tokenizer_cache_dir
            ),
            budget=budget,
            corpus_manifest_sha256=index_metadata["corpus_manifest_sha256"],
            stack_id="api",
            observer=observer,
            retrieval_top_k=args.retrieval_top_k,
            context_top_k=args.context_top_k,
        )
        trace_context = {
            "api_profile": args.api_profile,
            "index_config_sha256": index_config_hash,
        }
        if run_context is not None:
            trace_context.update(
                {
                    key: run_context[key]
                    for key in ("run_id", "case_id", "eval_set_sha256", "config_sha256")
                }
            )
        result = pipeline.query(request, trace_context=trace_context)
        write_json(
            output_path,
            {
                "response": result.response,
                "retrieval": result.retrieval,
                "timing_ms": result.timing_ms,
                "usage": result.usage,
                "cache_hit": result.cache_hit,
            },
        )
        if run_context is not None and run_record_output is not None:
            run_record = build_api_run_record(
                result,
                context=run_context,
                corpus_manifest_sha256=index_metadata["corpus_manifest_sha256"],
                generator_model=args.generator_model,
                embedding_model=index_metadata["embedding_model"],
                api_profile=args.api_profile,
                embedding_dimensions=index_metadata["dimensions"],
                index_config_sha256=index_config_hash,
                seed=generator.seed,
                temperature=generator.temperature,
                reasoning_effort=generator.reasoning_effort,
            )
            write_json(run_record_output, run_record)
        pipeline.flush_observability()
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        observer.flush()
        _print_failure(_safe_error_code(error, "query_failed"))
        return 7
    except Exception:
        observer.flush()
        _print_failure("query_failed")
        return 7
    summary = {
        "passed": result.response["status"] != "error",
        "request_id_hash": f"req_{hashlib.sha256(result.response['request_id'].encode('utf-8')).hexdigest()[:24]}",
        "status": result.response["status"],
        "citation_count": len(result.response["citations"]),
        "retrieval_count": len(result.retrieval),
        "total_ms": result.timing_ms["total"],
        "cost_usd": result.usage["cost_usd"],
        "trace_id": result.response["trace_id"],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["passed"] else 7


def _local_index_command(args: argparse.Namespace) -> int:
    from midprojectrag.indexing.embeddings import EmbeddingCache, embed_chunks
    from midprojectrag.indexing.exact_index import ExactDenseIndex
    from midprojectrag.stacks.local import LocalHashEmbeddingProvider, LocalTextCounter

    data_dir = args.data_dir.resolve()
    try:
        chunks, output_dir, cache_dir = _load_verified_index_inputs(
            args,
            data_dir,
            stack_id="local",
        )
        provider = LocalHashEmbeddingProvider()
        result = embed_chunks(
            chunks,
            provider=provider,
            counter=LocalTextCounter(),
            cache=EmbeddingCache(cache_dir),
            corpus_manifest_sha256=args.manifest_sha256,
            budget=None,
            batch_size=args.batch_size,
        )
        index = ExactDenseIndex(chunks, result.vectors, engine="numpy")
        metadata = index.save(
            output_dir,
            corpus_manifest_sha256=args.manifest_sha256,
            embedding_model=provider.model,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        _print_failure(_safe_error_code(error, "local_index_build_failed"))
        return 8
    except Exception:
        _print_failure("local_index_build_failed")
        return 8
    summary = {
        "passed": True,
        "stack_id": "mac_local_experimental",
        "engine": metadata["engine"],
        "embedding_model": metadata["embedding_model"],
        "chunks": metadata["count"],
        "dimensions": metadata["dimensions"],
        "cache_hits": result.cache_hits,
        "cache_misses": result.cache_misses,
        "input_characters": result.input_tokens,
        "cost_usd": 0.0,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _local_query_reproducibility(
    *,
    index_metadata: dict[str, Any],
    index_metadata_sha256: str,
    generator: Any,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Build text-free local run metadata from verified identifiers and settings."""

    hashes = {
        "corpus_manifest_sha256": require_sha256(
            index_metadata.get("corpus_manifest_sha256"),
            "invalid_corpus_manifest_hash",
        ),
        "chunk_artifact_sha256": require_sha256(
            index_metadata.get("chunk_artifact_sha256"),
            "invalid_chunk_artifact_hash",
        ),
        "chunk_config_sha256": require_sha256(
            index_metadata.get("chunk_config_sha256"),
            "invalid_chunk_config_hash",
        ),
        "index_metadata_sha256": require_sha256(
            index_metadata_sha256,
            "invalid_index_metadata_hash",
        ),
        "index_vectors_sha256": require_sha256(
            index_metadata.get("vectors_sha256"),
            "invalid_index_vectors_hash",
        ),
        "index_rows_sha256": require_sha256(
            index_metadata.get("rows_sha256"),
            "invalid_index_rows_hash",
        ),
    }
    query_config = {
        "schema_version": "1.0",
        "stack_id": "mac_local_experimental",
        "embedding_model": index_metadata["embedding_model"],
        "generator_model": generator.model,
        "generator_model_digest": generator.model_digest,
        "seed": generator.seed,
        "temperature": generator.temperature,
        "num_ctx": generator.context_tokens,
        "max_output_tokens": generator.max_output_tokens,
        "retrieval_top_k": args.retrieval_top_k,
        "context_top_k": args.context_top_k,
    }
    query_config_sha256 = hashlib.sha256(
        json.dumps(
            query_config,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        **hashes,
        "query_config_sha256": query_config_sha256,
        "query_config": query_config,
    }


def _local_query_command(args: argparse.Namespace) -> int:
    from midprojectrag.answering.pipeline import RagPipeline
    from midprojectrag.indexing.embeddings import EmbeddingCache
    from midprojectrag.indexing.exact_index import ExactDenseIndex
    from midprojectrag.observability import create_observer
    from midprojectrag.stacks.local import (
        LOCAL_HASH_EMBEDDING_DIMENSIONS,
        LOCAL_HASH_EMBEDDING_MODEL,
        LocalHashEmbeddingProvider,
        LocalTextCounter,
        OllamaGenerator,
    )

    observability = args.observability.strip().lower()
    if observability not in {"disabled", "memory"}:
        _print_failure("invalid_local_observability_backend")
        return 8
    observer = create_observer(observability)
    data_dir = args.data_dir.resolve()
    try:
        chunks_path = require_within(args.chunks.resolve(), data_dir, "chunks_path_outside_data_dir")
        index_dir = _require_stack_artifact_path(
            args.index_dir.resolve(),
            data_dir,
            stack_id="local",
            artifact_kind="indexes",
            error_code="local_index_path_outside_stack_root",
        )
        request_path = require_within(args.request.resolve(), data_dir, "request_path_outside_data_dir")
        output_path = _require_stack_artifact_path(
            args.output.resolve(),
            data_dir,
            stack_id="local",
            artifact_kind="outputs",
            error_code="local_query_output_outside_stack_root",
        )
        cache_dir = _require_stack_artifact_path(
            args.cache_dir.resolve(),
            data_dir,
            stack_id="local",
            artifact_kind="caches",
            error_code="local_cache_path_outside_stack_root",
        )
        generator = OllamaGenerator(
            model=args.generator_model,
            base_url=args.ollama_base_url,
            max_output_tokens=args.max_output_tokens,
            context_tokens=args.context_tokens,
            timeout_seconds=args.timeout_seconds,
        )
        chunks = read_jsonl(chunks_path)
        index_metadata_path = index_dir / "metadata.json"
        with index_metadata_path.open("r", encoding="utf-8") as source:
            index_metadata = json.load(source)
        if (
            index_metadata.get("embedding_model") != LOCAL_HASH_EMBEDDING_MODEL
            or index_metadata.get("dimensions") != LOCAL_HASH_EMBEDDING_DIMENSIONS
            or index_metadata.get("engine") != "numpy"
        ):
            raise ValueError("local_index_embedding_model_mismatch")
        with request_path.open("r", encoding="utf-8") as source:
            request = json.load(source)
        index = ExactDenseIndex.load(index_dir, chunks)
        embedding_provider = LocalHashEmbeddingProvider(
            dimensions=index_metadata.get("dimensions")
        )
        reproducibility = _local_query_reproducibility(
            index_metadata=index_metadata,
            index_metadata_sha256=sha256_file(index_metadata_path),
            generator=generator,
            args=args,
        )
        pipeline = RagPipeline(
            index=index,
            embedding_provider=embedding_provider,
            embedding_counter=LocalTextCounter(),
            query_cache=EmbeddingCache(cache_dir),
            generator=generator,
            generation_counter=LocalTextCounter(),
            budget=None,
            corpus_manifest_sha256=index_metadata["corpus_manifest_sha256"],
            observer=observer,
            retrieval_top_k=args.retrieval_top_k,
            context_top_k=args.context_top_k,
            stack_id="mac_local_experimental",
        )
        result = pipeline.query(request)
        write_json(
            output_path,
            {
                "stack_id": "mac_local_experimental",
                "embedding_model": index_metadata["embedding_model"],
                "generator_model": generator.model,
                "generator_model_digest": generator.model_digest,
                "response": result.response,
                "retrieval": result.retrieval,
                "timing_ms": result.timing_ms,
                "usage": result.usage,
                "cache_hit": result.cache_hit,
                "reproducibility": reproducibility,
            },
        )
        pipeline.flush_observability()
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        observer.flush()
        _print_failure(_safe_error_code(error, "local_query_failed"))
        return 8
    except Exception:
        observer.flush()
        _print_failure("local_query_failed")
        return 8
    summary = {
        "passed": result.response["status"] != "error",
        "stack_id": "mac_local_experimental",
        "generator_model_digest": generator.model_digest,
        "query_config_sha256": reproducibility["query_config_sha256"],
        "request_id_hash": (
            f"req_{hashlib.sha256(result.response['request_id'].encode('utf-8')).hexdigest()[:24]}"
        ),
        "status": result.response["status"],
        "citation_count": len(result.response["citations"]),
        "retrieval_count": len(result.retrieval),
        "total_ms": result.timing_ms["total"],
        "cost_usd": 0.0,
        "trace_id": result.response["trace_id"],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["passed"] else 8


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="midprojectrag")
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest = subparsers.add_parser("manifest", help="join CSV metadata to private source files")
    manifest.add_argument("--data-dir", type=Path, required=True)
    manifest.add_argument("--csv-path", type=Path)
    manifest.add_argument("--raw-dir", type=Path)
    manifest.add_argument("--output", type=Path)
    manifest.add_argument("--report", type=Path)
    manifest.add_argument("--expected-documents", type=_positive_int, default=98)
    manifest.add_argument("--expected-hwp", type=_positive_int, default=94)
    manifest.add_argument("--expected-pdf", type=_positive_int, default=4)
    manifest.set_defaults(handler=_manifest_command)

    correct_metadata = subparsers.add_parser(
        "correct-metadata",
        help="apply an evidence-backed private metadata correction overlay",
    )
    correct_metadata.add_argument("--data-dir", type=Path, required=True)
    correct_metadata.add_argument("--source-csv", type=Path)
    correct_metadata.add_argument("--corrections", type=Path, required=True)
    correct_metadata.add_argument("--output", type=Path)
    correct_metadata.add_argument("--report", type=Path)
    correct_metadata.set_defaults(handler=_correct_metadata_command)

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
    verify.add_argument("--expected-documents", type=_positive_int, default=98)
    verify.add_argument("--expected-hwp", type=_positive_int, default=94)
    verify.add_argument("--expected-pdf", type=_positive_int, default=4)
    verify.add_argument("--require-extracted", action="store_true")
    verify.add_argument(
        "--require-primary-hwp",
        action="store_true",
        help="require every HWP/HWPX to be ok under pinned rhwp and verify block files",
    )
    verify.add_argument(
        "--rhwp-sha256",
        help="allowlisted rhwp executable SHA-256 required by --require-primary-hwp",
    )
    verify.add_argument("--max-failed", type=_positive_int, default=0)
    verify.set_defaults(handler=_verify_command)

    visual_gold = subparsers.add_parser(
        "visual-gold-validate",
        help="validate private HWP/PDF representative visual annotations",
    )
    visual_gold.add_argument("--data-dir", type=Path, required=True)
    visual_gold.add_argument("--annotations", type=Path, required=True)
    visual_gold.add_argument(
        "--allow-draft",
        action="store_true",
        help="allow unreviewed annotations for incremental authoring",
    )
    visual_gold.add_argument(
        "--partial",
        action="store_true",
        help="validate record contracts without requiring the full 5-HWP/4-PDF gate",
    )
    visual_gold.set_defaults(handler=_visual_gold_validate_command)

    pdf_visual_v2 = subparsers.add_parser(
        "pdf-visual-v2",
        help="materialize deterministic local PDF resource, placement and crop evidence",
    )
    pdf_visual_v2.add_argument("--data-dir", type=Path, required=True)
    pdf_visual_v2.add_argument("--manifest", type=Path, required=True)
    pdf_visual_v2.add_argument("--output-dir", type=Path, required=True)
    pdf_visual_v2.add_argument("--private-root", type=Path)
    pdf_visual_v2.add_argument("--render-scale", type=_positive_float, default=2.0)
    pdf_visual_v2.add_argument("--expected-artifact-set-id")
    pdf_visual_v2.set_defaults(handler=_pdf_visual_v2_command)

    hwp_visual_v2 = subparsers.add_parser(
        "hwp-visual-v2",
        help="materialize local HWP occurrence/object/crop evidence with pinned rhwp",
    )
    hwp_visual_v2.add_argument("--data-dir", type=Path, required=True)
    hwp_visual_v2.add_argument("--manifest", type=Path, required=True)
    hwp_visual_v2.add_argument("--blocks-dir", type=Path, required=True)
    hwp_visual_v2.add_argument("--selection", type=Path, required=True)
    hwp_visual_v2.add_argument("--output-dir", type=Path, required=True)
    hwp_visual_v2.add_argument("--private-root", type=Path)
    hwp_visual_v2.add_argument("--node-executable", type=Path, required=True)
    hwp_visual_v2.add_argument("--node-sha256", type=_sha256_hex, required=True)
    hwp_visual_v2.add_argument("--helper", type=Path, required=True)
    hwp_visual_v2.add_argument("--helper-sha256", type=_sha256_hex, required=True)
    hwp_visual_v2.add_argument("--core-js", type=Path, required=True)
    hwp_visual_v2.add_argument("--core-js-sha256", type=_sha256_hex, required=True)
    hwp_visual_v2.add_argument("--wasm", type=Path, required=True)
    hwp_visual_v2.add_argument("--wasm-sha256", type=_sha256_hex, required=True)
    hwp_visual_v2.add_argument("--canvas-module", type=Path, required=True)
    hwp_visual_v2.add_argument(
        "--canvas-module-sha256", type=_sha256_hex, required=True
    )
    hwp_visual_v2.add_argument(
        "--mode", choices=("representative", "corpus"), default="representative"
    )
    hwp_visual_v2.add_argument("--visual-gold", type=Path)
    hwp_visual_v2.add_argument(
        "--timeout-seconds", type=_positive_float, default=180.0
    )
    hwp_visual_v2.add_argument("--expected-artifact-set-id")
    hwp_visual_v2.set_defaults(handler=_hwp_visual_v2_command)

    visual_understanding = subparsers.add_parser(
        "visual-understand",
        help="run checksum-pinned offline OCR and optional caption evidence",
    )
    visual_understanding.add_argument("--private-root", type=Path, required=True)
    visual_understanding.add_argument("--occurrences", type=Path, required=True)
    visual_understanding.add_argument("--output-root", type=Path, required=True)
    visual_understanding.add_argument("--ocr-config", type=Path, required=True)
    visual_understanding.add_argument("--ocr-command", type=Path, required=True)
    visual_understanding.add_argument(
        "--ocr-command-sha256", type=_sha256_hex, required=True
    )
    visual_understanding.add_argument(
        "--ocr-model-artifact", type=Path, required=True
    )
    visual_understanding.add_argument(
        "--network-sandbox-backend",
        choices=("darwin-sandbox-exec-v1", "linux-bwrap-v1"),
        required=True,
        help="OS-level network sandbox used for every OCR/caption subprocess",
    )
    visual_understanding.add_argument(
        "--network-sandbox-command", type=Path, required=True
    )
    visual_understanding.add_argument(
        "--network-sandbox-command-sha256", type=_sha256_hex, required=True
    )
    visual_understanding.add_argument(
        "--ocr-argument", action="append", default=[]
    )
    visual_understanding.add_argument("--caption-config", type=Path)
    visual_understanding.add_argument("--caption-command", type=Path)
    visual_understanding.add_argument(
        "--caption-command-sha256", type=_sha256_hex
    )
    visual_understanding.add_argument("--caption-model-artifact", type=Path)
    visual_understanding.add_argument(
        "--caption-argument", action="append", default=[]
    )
    visual_understanding.add_argument(
        "--adapter-timeout-seconds", type=_positive_float, default=120.0
    )
    visual_understanding.add_argument("--ocr-weight", type=float, default=1.0)
    visual_understanding.add_argument("--layout-weight", type=float, default=0.8)
    visual_understanding.add_argument("--caption-weight", type=float, default=0.35)
    visual_understanding.add_argument(
        "--caption-per-query", type=_positive_int, default=2
    )
    visual_understanding.add_argument(
        "--caption-per-document", type=_positive_int, default=1
    )
    visual_understanding.set_defaults(handler=_visual_understanding_command)

    chunk = subparsers.add_parser("chunk", help="build deterministic primary page chunks")
    chunk.add_argument("--data-dir", type=Path, required=True)
    chunk.add_argument("--manifest", type=Path, required=True)
    chunk.add_argument("--blocks-dir", type=Path, required=True)
    chunk.add_argument("--output", type=Path, required=True)
    chunk.add_argument("--max-chars", type=_positive_int, default=24_000)
    chunk.set_defaults(handler=_chunk_command)

    table_layout = subparsers.add_parser(
        "table-layout",
        help="build a verified rhwp table-to-page layout overlay",
    )
    table_layout.add_argument("--data-dir", type=Path, required=True)
    table_layout.add_argument("--manifest", type=Path, required=True)
    table_layout.add_argument("--blocks-dir", type=Path, required=True)
    table_layout.add_argument("--output", type=Path, required=True)
    table_layout.add_argument("--timeout-seconds", type=_strict_positive_int, default=120)
    table_layout.set_defaults(handler=_table_layout_command)

    hwp_visual_corpus = subparsers.add_parser(
        "hwp-visual-corpus",
        help="materialize or strictly reuse private HWP visual evidence bundles",
    )
    hwp_visual_corpus.add_argument("--data-dir", type=Path, required=True)
    hwp_visual_corpus.add_argument("--manifest", type=Path, required=True)
    hwp_visual_corpus.add_argument("--blocks-dir", type=Path, required=True)
    hwp_visual_corpus.add_argument("--layout-overlay", type=Path, required=True)
    hwp_visual_corpus.add_argument("--selection", type=Path, required=True)
    hwp_visual_corpus.add_argument("--private-root", type=Path)
    hwp_visual_corpus.add_argument("--output-root", type=Path)
    hwp_visual_corpus.add_argument("--asset-root", type=Path)
    hwp_visual_corpus.add_argument("--report-output", type=Path)
    hwp_visual_corpus.add_argument("--mode", choices=("sample", "corpus"), required=True)
    hwp_visual_corpus.add_argument("--expected-hwp", type=_strict_positive_int, default=94)
    hwp_visual_corpus.add_argument("--timeout-seconds", type=_strict_positive_int, default=120)
    hwp_visual_corpus.add_argument("--continue-on-error", action="store_true")
    hwp_visual_corpus.set_defaults(handler=_hwp_visual_corpus_command)

    hwp_visual_select = subparsers.add_parser(
        "hwp-visual-select",
        help="select five numeric-only HWP structural risk representatives",
    )
    hwp_visual_select.add_argument("--data-dir", type=Path, required=True)
    hwp_visual_select.add_argument("--manifest", type=Path, required=True)
    hwp_visual_select.add_argument("--blocks-dir", type=Path, required=True)
    hwp_visual_select.add_argument("--layout-overlay", type=Path, required=True)
    hwp_visual_select.add_argument("--output", type=Path, required=True)
    hwp_visual_select.add_argument("--private-root", type=Path)
    hwp_visual_select.add_argument("--existing-visual-root", type=Path)
    hwp_visual_select.add_argument("--expected-hwp", type=_strict_positive_int, default=94)
    hwp_visual_select.set_defaults(handler=_hwp_visual_select_command)

    visual_table_corpus = subparsers.add_parser(
        "visual-table-corpus",
        help="build one corpus-wide table-md-visual-context-v2 artifact",
    )
    visual_table_corpus.add_argument("--data-dir", type=Path, required=True)
    visual_table_corpus.add_argument("--source-chunks", type=Path, required=True)
    visual_table_corpus.add_argument("--corpus-metadata", type=Path, required=True)
    visual_table_corpus.add_argument("--output", type=Path, required=True)
    visual_table_corpus.add_argument("--metadata-output", type=Path)
    visual_table_corpus.add_argument("--private-root", type=Path)
    visual_table_corpus.add_argument("--overlay-root", type=Path)
    visual_table_corpus.set_defaults(handler=_visual_table_corpus_command)

    table_chunk = subparsers.add_parser(
        "table-chunk", help="build deterministic structured Markdown table chunks"
    )
    table_chunk.add_argument("--data-dir", type=Path, required=True)
    table_chunk.add_argument("--manifest", type=Path, required=True)
    table_chunk.add_argument("--blocks-dir", type=Path, required=True)
    table_chunk.add_argument("--output", type=Path, required=True)
    table_chunk.add_argument("--tokenizer-cache-dir", type=Path, required=True)
    table_chunk.add_argument("--layout-overlay", type=Path)
    table_chunk.add_argument("--max-rows", type=_strict_positive_int, default=8)
    table_chunk.add_argument("--max-chars", type=_strict_positive_int, default=2_400)
    table_chunk.add_argument("--max-tokens", type=_strict_positive_int, default=600)
    table_chunk.add_argument("--summary-chars", type=_positive_int, default=320)
    table_chunk.set_defaults(handler=_table_chunk_command)

    tokenizer_cache = subparsers.add_parser(
        "tokenizer-cache",
        help="download and hash-verify allowlisted public tiktoken vocab assets",
    )
    tokenizer_cache.add_argument("--data-dir", type=Path, required=True)
    tokenizer_cache.add_argument("--cache-dir", type=Path)
    tokenizer_cache.add_argument("--approve-static-tokenizer-download", action="store_true")
    tokenizer_cache.set_defaults(handler=_tokenizer_cache_command)

    index = subparsers.add_parser("index", help="embed chunks and build an exact dense index")
    index.add_argument("--data-dir", type=Path, required=True)
    index.add_argument("--chunks", type=Path, required=True)
    index.add_argument("--output-dir", type=Path, required=True)
    index.add_argument("--cache-dir", type=Path, required=True)
    index.add_argument("--tokenizer-cache-dir", type=Path)
    index.add_argument("--budget-ledger", type=Path, required=True)
    index.add_argument("--manifest", type=Path)
    index.add_argument("--chunk-metadata", type=Path)
    index.add_argument("--manifest-sha256", type=_sha256_hex, required=True)
    index.add_argument(
        "--api-profile",
        choices=_API_PROFILES,
        default=_allowlisted_model_env(
            "MIDPROJECTRAG_API_PROFILE",
            choices=_API_PROFILES,
            default="assignment",
            error_code="api_profile_not_allowlisted",
        ),
    )
    index.add_argument(
        "--model",
        choices=_API_EMBEDDING_MODELS,
        default=_allowlisted_model_env(
            "MIDPROJECTRAG_API_EMBEDDING_MODEL",
            choices=_API_EMBEDDING_MODELS,
            default="text-embedding-3-small",
            error_code="embedding_model_not_allowlisted",
        ),
    )
    index.add_argument("--dimensions", type=_strict_positive_int)
    index.add_argument("--batch-size", type=_positive_int, default=128)
    index.add_argument(
        "--batch-interval-seconds",
        type=_nonnegative_float,
        default=0.0,
        help="minimum start-to-start interval between embedding API batches",
    )
    index.add_argument("--engine", choices=("faiss", "numpy"), default="faiss")
    index.add_argument(
        "--max-api-budget-usd",
        type=_positive_float,
        default=float(os.getenv("MIDPROJECTRAG_MAX_API_BUDGET_USD", "20")),
    )
    index.add_argument("--approve-external-corpus-egress", action="store_true")
    index.set_defaults(handler=_index_command)

    migrate_index_subset = subparsers.add_parser(
        "migrate-index-subset",
        help="reuse a verified API index for a byte-identical page-chunk subset",
    )
    migrate_index_subset.add_argument("--source-data-dir", type=Path, required=True)
    migrate_index_subset.add_argument("--source-chunks", type=Path, required=True)
    migrate_index_subset.add_argument("--source-index-dir", type=Path, required=True)
    migrate_index_subset.add_argument("--target-data-dir", type=Path, required=True)
    migrate_index_subset.add_argument("--target-chunks", type=Path, required=True)
    migrate_index_subset.add_argument("--target-chunk-metadata", type=Path)
    migrate_index_subset.add_argument("--target-manifest", type=Path, required=True)
    migrate_index_subset.add_argument(
        "--target-manifest-sha256",
        type=_sha256_hex,
        required=True,
    )
    migrate_index_subset.add_argument("--output-dir", type=Path, required=True)
    migrate_index_subset.set_defaults(handler=_migrate_index_subset_command)

    query = subparsers.add_parser("query", help="run one citation-safe API baseline query")
    query.add_argument("--data-dir", type=Path, required=True)
    query.add_argument("--chunks", type=Path, required=True)
    query.add_argument("--index-dir", type=Path, required=True)
    query.add_argument("--request", type=Path, required=True)
    query.add_argument("--output", type=Path, required=True)
    query.add_argument("--cache-dir", type=Path, required=True)
    query.add_argument("--tokenizer-cache-dir", type=Path)
    query.add_argument("--budget-ledger", type=Path, required=True)
    query.add_argument(
        "--run-context",
        type=Path,
        help="private reproducibility metadata JSON; requires --run-record-output",
    )
    query.add_argument(
        "--run-record-output",
        type=Path,
        help="write an evaluator-compatible private run record inside --data-dir",
    )
    query.add_argument(
        "--api-profile",
        choices=_API_PROFILES,
        default=_allowlisted_model_env(
            "MIDPROJECTRAG_API_PROFILE",
            choices=_API_PROFILES,
            default="assignment",
            error_code="api_profile_not_allowlisted",
        ),
    )
    query.add_argument(
        "--generator-model",
        choices=_API_GENERATOR_MODELS,
        default=_allowlisted_model_env(
            "MIDPROJECTRAG_API_GENERATOR_MODEL",
            choices=_API_GENERATOR_MODELS,
            default="gpt-5-mini",
            error_code="generator_model_not_allowlisted",
        ),
    )
    query.add_argument("--max-output-tokens", type=_positive_int, default=1200)
    query.add_argument("--retrieval-top-k", type=_positive_int, default=10)
    query.add_argument("--context-top-k", type=_positive_int, default=5)
    query.add_argument(
        "--max-api-budget-usd",
        type=_positive_float,
        default=float(os.getenv("MIDPROJECTRAG_MAX_API_BUDGET_USD", "20")),
    )
    query.add_argument(
        "--observability",
        choices=("disabled", "memory", "langfuse"),
        default=os.getenv("MIDPROJECTRAG_OBSERVABILITY", "disabled").strip().lower(),
    )
    query.add_argument("--approve-external-corpus-egress", action="store_true")
    query.add_argument("--approve-langfuse-metadata-egress", action="store_true")
    query.set_defaults(handler=_query_command)

    local_index = subparsers.add_parser(
        "local-index",
        help="build the offline deterministic hash index for Mac exploration",
    )
    local_index.add_argument("--data-dir", type=Path, required=True)
    local_index.add_argument("--chunks", type=Path, required=True)
    local_index.add_argument("--output-dir", type=Path, required=True)
    local_index.add_argument("--cache-dir", type=Path, required=True)
    local_index.add_argument("--manifest", type=Path)
    local_index.add_argument("--chunk-metadata", type=Path)
    local_index.add_argument("--manifest-sha256", type=_sha256_hex, required=True)
    local_index.add_argument("--batch-size", type=_positive_int, default=256)
    local_index.set_defaults(handler=_local_index_command)

    local_query = subparsers.add_parser(
        "local-query",
        help="run one loopback-only Qwen3.8 exploratory query",
    )
    local_query.add_argument("--data-dir", type=Path, required=True)
    local_query.add_argument("--chunks", type=Path, required=True)
    local_query.add_argument("--index-dir", type=Path, required=True)
    local_query.add_argument("--request", type=Path, required=True)
    local_query.add_argument("--output", type=Path, required=True)
    local_query.add_argument("--cache-dir", type=Path, required=True)
    local_query.add_argument(
        "--generator-model",
        choices=("qwen3.8:27b-mlx",),
        default="qwen3.8:27b-mlx",
    )
    local_query.add_argument("--ollama-base-url", default="http://127.0.0.1:11434")
    local_query.add_argument("--max-output-tokens", type=_positive_int, default=1200)
    local_query.add_argument("--context-tokens", type=_positive_int, default=16384)
    local_query.add_argument("--timeout-seconds", type=_positive_float, default=180.0)
    local_query.add_argument("--retrieval-top-k", type=_positive_int, default=10)
    local_query.add_argument("--context-top-k", type=_positive_int, default=5)
    local_query.add_argument(
        "--observability",
        choices=("disabled", "memory"),
        default="disabled",
    )
    local_query.set_defaults(handler=_local_query_command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _load_project_dotenv()
    try:
        parser = build_parser()
    except ValueError as error:
        _print_failure(_safe_error_code(error, "invalid_cli_environment"))
        return 2
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
