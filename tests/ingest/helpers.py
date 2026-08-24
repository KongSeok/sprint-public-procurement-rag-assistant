from __future__ import annotations

import csv
from pathlib import Path

from midprojectrag.ingest.manifest import CFB_SIGNATURE, CSV_COLUMNS


def write_hwp_stub(path: Path, payload: bytes = b"synthetic") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(CFB_SIGNATURE + payload)


def write_metadata_csv(path: Path, filenames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(CSV_COLUMNS.values()))
        writer.writeheader()
        for index, filename in enumerate(filenames, start=1):
            writer.writerow(
                {
                    "공고 번호": f"NOTICE-{index:03d}",
                    "공고 차수": "0",
                    "사업명": f"합성 사업 {index}",
                    "사업 금액": "1000000",
                    "발주 기관": "합성 기관",
                    "공개 일자": "2026-01-01 00:00:00",
                    "입찰 참여 시작일": "2026-01-02 00:00:00",
                    "입찰 참여 마감일": "2026-01-03 00:00:00",
                    "사업 요약": "공개 테스트용 합성 요약",
                    "파일형식": Path(filename).suffix.lstrip("."),
                    "파일명": filename,
                    "텍스트": "검색 본문으로 사용하지 않는 합성 미리보기",
                }
            )
