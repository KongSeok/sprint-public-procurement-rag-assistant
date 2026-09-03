"""240초 타임아웃으로도 여전히 표 추출이 실패하는 소수 문서만, 훨씬 큰
타임아웃(기본 600초)으로 개별 재시도해서 output/merged_docs.pkl에 그 문서
행만 패치한다 - 98건 전체를 다시 재파싱할 필요 없이 몇 분 안에 끝난다.

[배경] 14절 패치(90초 -> 240초)로 타임아웃 문서가 35건 -> 3건까지 줄었다
(scripts/diagnose_table_extraction_stability.py로 확인). 남은 3건은:
  - KOICA 전자조달_[긴급] [지문] [국제] 우즈베키스탄 열린 의정활동 상하원 .hwp
  - 그랜드코리아레저(주)_2024년도 GKL  그룹웨어 시스템 구축 용역.hwp
  - 한국산업단지공단_산단 안전정보시스템 1차 구축 용역.hwp
35 -> 3으로 대부분이 "시스템이 그 순간 바빴을 뿐"인 부하성 타임아웃이었다는
가설을 뒷받침하지만, 이 3건은 240초를 두 번째 시도에서도 넘겼으므로 정말
예외적으로 크거나 복잡한 문서일 가능성이 있다.

이 스크립트는 hwp_parser.parse_hwp(..., tables_timeout=600)으로 이 3건만
다시 시도하고, merge_text.merge_one()과 동일한 후처리(inline 삽입 시도 ->
실패시 중복 필터링 후 문서 끝 첨부 폴백)를 거쳐 결과를 만든 다음,
output/merged_docs.pkl에서 이 문서들의 행만 교체해서 저장한다 - 나머지
95건은 이미 좋은 결과를 갖고 있으므로 건드리지 않는다.

사용법: python scripts/reextract_slow_tables.py
(원하면 파일명을 인자로 직접 줘서 다른 문서를 재시도할 수도 있다:
 python scripts/reextract_slow_tables.py "어떤파일.hwp" --timeout 900)
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import RAW_FILES_DIR  # noqa: E402
from src.data_processing.load_metadata import load_clean_metadata  # noqa: E402
from src.data_processing.merge_text import (  # noqa: E402
    MergedDoc,
    _filter_duplicate_tables,
    _flatten_tables,
    _insert_tables_inline,
    _strip_table_placeholders,
    load_merged,
    save_merged,
)
from src.data_processing.parsers import classify, hwp_parser  # noqa: E402

DEFAULT_TARGETS = [
    "KOICA 전자조달_[긴급] [지문] [국제] 우즈베키스탄 열린 의정활동 상하원 .hwp",
    "그랜드코리아레저(주)_2024년도 GKL  그룹웨어 시스템 구축 용역.hwp",
    "한국산업단지공단_산단 안전정보시스템 1차 구축 용역.hwp",
]


def _reparse_one(file_name: str, timeout: int) -> MergedDoc:
    """merge_text.merge_one()의 hwp 성공 경로를 그대로 재현하되, 표 추출
    타임아웃만 훨씬 크게(기본 600초) 준다."""
    path = RAW_FILES_DIR / file_name
    doc_id = file_name
    if not path.exists():
        raise FileNotFoundError(f"원본 파일을 찾을 수 없음: {path}")

    t0 = time.time()
    parsed = hwp_parser.parse_hwp(path, extract_tables_flag=True, tables_timeout=timeout)
    elapsed = time.time() - t0
    print(f"    파싱 소요시간: {elapsed:.1f}초")

    if not parsed.ok:
        raise RuntimeError(f"재파싱 실패: {parsed.error}")

    raw_text = parsed.text.strip()
    if not raw_text:
        raise RuntimeError("재파싱 결과가 빈 텍스트")

    cls = classify.classify_with_parse_result(
        text_len=len(raw_text), n_tables=parsed.n_tables,
        n_pages=getattr(parsed, "n_pages", None),
        n_scanned_pages=getattr(parsed, "n_scanned_pages", None),
        used_ocr=getattr(parsed, "used_ocr", False),
    )

    accept_note = f"원본 재파싱 채택 (개별 재시도, timeout={timeout}초)"
    table_note = getattr(parsed, "table_note", None)
    if table_note:
        accept_note += f" | 표: {table_note}"

    tables = getattr(parsed, "tables", None) or []
    inline_text, inline_ok = _insert_tables_inline(raw_text, tables)
    if inline_ok:
        full_text = inline_text
        if tables:
            accept_note += " | 표 내용을 원래 위치에 끼워넣음(inline, 문맥 유지)"
    else:
        kept_tables, n_dropped_dup = _filter_duplicate_tables(tables, raw_text)
        table_text = _flatten_tables(kept_tables)
        full_text = _strip_table_placeholders(raw_text) + table_text
        if tables:
            n_placeholders = sum(1 for ln in raw_text.split("\n") if ln.strip() == "<표>")
            dup_note = f", 본문과 완전중복인 표 {n_dropped_dup}/{len(tables)}개는 제외" if n_dropped_dup else ""
            accept_note += (
                f" | 표 자리표시자 개수({n_placeholders})와 추출된 표 개수({len(tables)}) 불일치"
                f" -> inline 삽입 포기, 표 내용을 문서 끝에 일괄 첨부(폴백{dup_note})"
            )

    return MergedDoc(
        doc_id=doc_id, text=full_text, n_tables=parsed.n_tables,
        source="raw_parsed", doc_type=cls.doc_type,
        doc_type_confidence=cls.confidence, doc_type_reason=cls.reason,
        parse_note=accept_note,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="재시도할 파일명(들). 생략하면 기본 3건.")
    ap.add_argument("--timeout", type=int, default=600, help="표 추출 타임아웃(초), 기본 600")
    args = ap.parse_args()

    targets = args.files or DEFAULT_TARGETS

    df = load_merged()
    if df is None:
        print("output/merged_docs.pkl 캐시가 없습니다 - step2_merge_text.py를 먼저 실행해주세요.")
        return

    # doc_id -> 파일명 매핑 확인용 (doc_id가 파일명과 동일하다고 가정하지만,
    # load_clean_metadata()로 실제 존재 여부를 한 번 더 확인한다)
    meta = load_clean_metadata()
    known_ids = set(meta["doc_id"])

    for file_name in targets:
        print(f"\n{'=' * 100}\n재시도: {file_name}")
        if file_name not in known_ids:
            print(f"  !! doc_id를 찾을 수 없음(파일명이 정확한지 확인): {file_name}")
            continue
        if file_name not in set(df["doc_id"]):
            print("  !! output/merged_docs.pkl에 이 doc_id가 없음(중복 제외됐거나 오탈자) - 건너뜀")
            continue

        old_row = df.loc[df["doc_id"] == file_name].iloc[0]
        print(f"  기존: n_tables={old_row['n_tables']}, parse_note={old_row['parse_note']}")

        try:
            new_doc = _reparse_one(file_name, timeout=args.timeout)
        except Exception as e:  # noqa: BLE001
            print(f"  !! 재시도 실패: {e}")
            continue

        print(f"  신규: n_tables={new_doc.n_tables}, parse_note={new_doc.parse_note}")

        idx = df.index[df["doc_id"] == file_name][0]
        for field in ("text", "n_tables", "source", "doc_type", "doc_type_confidence", "doc_type_reason", "parse_note"):
            df.at[idx, field] = getattr(new_doc, field)

    save_merged(df)
    print(f"\n{'=' * 100}\n패치 완료. output/merged_docs.pkl 갱신됨 - 이 스크립트는 나머지 문서는 건드리지 않았음.")
    print("확인: python scripts/diagnose_table_extraction_stability.py 를 다시 돌려서 타임아웃 건수가 줄었는지 볼 것.")


if __name__ == "__main__":
    main()
