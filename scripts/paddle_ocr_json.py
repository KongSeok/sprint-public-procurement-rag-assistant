"""Entrypoint invoked by the checksum-pinned isolated Python interpreter (-I)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from midprojectrag.ingest.paddle_ocr_runtime import main

if __name__ == "__main__":
    raise SystemExit(main())
