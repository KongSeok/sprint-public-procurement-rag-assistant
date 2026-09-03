"""hwp 표 추출 진단용 스크립트. 실제 hwp 파일 1개를 놓고

  1. hwp5html 변환이 실제로 몇 초 걸리는지
  2. 변환된 HTML 안에 <table> 태그가 있긴 한지
  3. 우리 코드(BeautifulSoup)가 그 표에서 행/열을 제대로 뽑아내는지

를 순서대로 확인한다. 결과 HTML은 output/debug_hwp5html/ 아래 남겨서
필요하면 직접 열어볼 수 있게 한다(파이프라인에서 쓰는 임시폴더와 달리
지우지 않음).

사용법 - 파이참에서 우클릭 > Run으로 바로 실행하면 됨(인자 불필요).
아래 TARGET_FILENAME에 테스트하고 싶은 파일명을 적어두면 그 파일을 쓰고,
없으면 아래 이유로 미리 골라둔 후보(표가 있을 가능성이 높다고 텍스트에서
확인된 문서)를 자동으로 찾아서 쓴다. 터미널에서 다른 파일을 지정하고 싶으면:
    python scripts/diagnose_hwp_table.py "data/files/파일명.hwp"
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import RAW_FILES_DIR, OUTPUT_DIR  # noqa: E402

# 여기에 파일명(확장자 포함)을 적으면 그 파일로 테스트한다. 비워두면(None)
# 아래 PREFERRED_CANDIDATES 순서대로 찾아서 첫 번째로 존재하는 파일을 쓴다.
TARGET_FILENAME: str | None = None

# CSV 텍스트에서 이미 "SER-001 보안 공통사항" 같은 요구사항 정의서 항목 목록이나
# 총액/분납 예산 구조가 확인돼서, 원본에 실제 표가 있을 가능성이 높다고 본 문서들.
# 표 추출이 정말 실패하는지(버그) 아니면 이 문서들엔 진짜 표가 없는지 확인하기 좋은 표본.
PREFERRED_CANDIDATES = [
    "한국생산기술연구원_2세대 전자조달시스템  기반구축사업.hwp",
    "경희대학교_[입찰공고] 산학협력단 정보시스템 운영 용역업체 선정.hwp",
    "한국철도공사 (용역)_모바일오피스 시스템 고도화 용역(총체 및 1차).hwp",
]


def pick_target() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    if TARGET_FILENAME:
        path = RAW_FILES_DIR / TARGET_FILENAME
        if path.exists():
            print(f"TARGET_FILENAME으로 지정된 파일 사용: {path.name}")
            return path
        print(f"TARGET_FILENAME '{TARGET_FILENAME}'을 data/files/에서 찾지 못함 -> 후보 목록으로 대체")
    for name in PREFERRED_CANDIDATES:
        path = RAW_FILES_DIR / name
        if path.exists():
            print(f"표가 있을 가능성이 높은 후보 자동 선택: {path.name}")
            return path
    candidates = sorted(RAW_FILES_DIR.glob("*.hwp"))
    if not candidates:
        print(f"data/files/ 안에 hwp 파일이 없습니다: {RAW_FILES_DIR}")
        sys.exit(1)
    print(f"미리 골라둔 후보가 data/files/에 없어서 첫 번째 hwp 자동 선택: {candidates[0].name}")
    return candidates[0]


def main():
    target = pick_target()
    if not target.exists():
        print(f"파일을 찾을 수 없습니다: {target}")
        sys.exit(1)
    print(f"대상 파일: {target}  (크기: {target.stat().st_size / 1024:.0f} KB)")

    # --- 1. hwp5txt 텍스트 추출 시간 ---
    print("\n[1] hwp5txt 텍스트 추출 시도...")
    t0 = time.time()
    try:
        proc = subprocess.run(
            ["hwp5txt", str(target)], capture_output=True, timeout=300,
            encoding="utf-8", errors="replace",
        )
        elapsed = time.time() - t0
        if proc.returncode == 0:
            print(f"    완료: {elapsed:.1f}초, 텍스트 길이 {len(proc.stdout)}자")
        else:
            print(f"    실패({elapsed:.1f}초): {proc.stderr.strip()[:300]}")
    except subprocess.TimeoutExpired:
        print(f"    300초 넘게 걸려서 중단함 -> 이 파일은 hwp5txt 자체가 매우 느림")

    # --- 2. hwp5html 표 변환 시간 (제한시간 넉넉하게 300초) ---
    print("\n[2] hwp5html 표 변환 시도 (최대 300초 대기)...")
    debug_dir = OUTPUT_DIR / "debug_hwp5html" / target.stem
    debug_dir.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        proc = subprocess.run(
            ["hwp5html", "--output", str(debug_dir), str(target)],
            capture_output=True, timeout=300, encoding="utf-8", errors="replace",
        )
        elapsed = time.time() - t0
        if proc.returncode != 0:
            print(f"    실패({elapsed:.1f}초): {proc.stderr.strip()[:500]}")
            return
        print(f"    완료: {elapsed:.1f}초")
        print(f"    결과 폴더 (직접 열어볼 수 있음): {debug_dir}")
    except subprocess.TimeoutExpired:
        print(f"    300초 넘게 걸려서 중단함 -> hwp5html이 이 파일에서 멈추거나 매우 느림")
        print(f"    (기본 파이프라인은 20초 제한이라 이런 파일은 항상 표 추출 실패로 처리됨)")
        return

    # --- 3. <table> 태그 존재 여부 + 우리 파싱 로직으로 실제 추출되는지 ---
    print("\n[3] 변환된 HTML에서 표 추출 확인...")
    index_html = debug_dir / "index.xhtml"
    if not index_html.exists():
        candidates = list(debug_dir.glob("*.xhtml")) + list(debug_dir.glob("*.html"))
        if not candidates:
            print("    hwp5html 출력 파일(xhtml/html)을 찾지 못함")
            return
        index_html = candidates[0]

    from bs4 import BeautifulSoup
    html_text = index_html.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html_text, "lxml-xml")
    raw_tables = soup.find_all("table")
    print(f"    <table> 태그 개수(원본): {len(raw_tables)}")

    tables = []
    for table_tag in raw_tables:
        rows = []
        for tr in table_tag.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    print(f"    실제 행(row)이 있는 표 개수: {len(tables)}")

    if tables:
        print("\n    첫 번째 표 미리보기 (최대 5행):")
        for row in tables[0][:5]:
            print("     ", row)
    elif raw_tables:
        print("\n    <table> 태그는 있는데 우리 코드가 행을 못 뽑고 있음 -> 파싱 로직 버그 의심")
        print("    첫 번째 <table> 태그 원본(500자):")
        print("    ", str(raw_tables[0])[:500])
    else:
        print("\n    이 문서엔 hwp5html이 표를 아예 인식하지 못한 것으로 보임")
        print(f"    {index_html} 파일을 직접 열어서 원본 구조를 확인해볼 수 있음")


if __name__ == "__main__":
    main()
