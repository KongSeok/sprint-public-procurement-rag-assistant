"""Private corpus ingestion primitives."""

from midprojectrag.ingest.manifest import build_manifest
from midprojectrag.ingest.verify import verify_manifest

__all__ = ["build_manifest", "verify_manifest"]
