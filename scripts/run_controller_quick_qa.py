"""Compatibility launcher; all requests now use the hotline-only runtime."""
from midprojectrag.hotline import (
    BASE_URL, MODEL, ROOT, SYSTEM, TOTAL_BUDGET_SECONDS,
    DurableJournal, RecordingOpener, Timer, digest, execute_question,
    fixed_public_pipeline, initialize, lazy_provider_after_device_probe, main,
    parent_context, remaining_http_timeout, remaining_timeout_ms, validate_answer,
    write_json,
)

if __name__ == "__main__":
    raise SystemExit(main())
