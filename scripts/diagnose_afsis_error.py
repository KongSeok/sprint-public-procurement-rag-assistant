"""한국농어촌공사 AFSIS 문서에서 hwp5txt가 실패하는 원인(전체 traceback)을 보기
위한 1회성 진단 스크립트.

터미널에서 hwp5txt를 직접 치면 PowerShell의 따옴표/멀티라인 붙여넣기 문제로
계속 꼬여서, 파이썬 subprocess로 대신 돌려 stderr 전체를 콘솔과 파일 둘 다에
남기도록 만들었다. 파이참에서 우클릭 > Run으로 실행하면 된다(인자 불필요).
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import OUTPUT_DIR, RAW_FILES_DIR  # noqa: E402

TARGET = RAW_FILES_DIR / "한국농어촌공사_아세안+3 식량안보정보시스템(AFSIS) 3단계 협력(캄보디아.hwp"


def main():
    if not TARGET.exists():
        print(f"파일을 찾을 수 없음: {TARGET}")
        print("data/files/ 안의 실제 파일명과 위 경로가 정확히 일치하는지 확인해줘.")
        sys.exit(1)

    print(f"대상 파일: {TARGET}")
    print(f"파일 크기: {TARGET.stat().st_size / 1024:.0f} KB\n")

    proc = subprocess.run(
        ["hwp5txt", str(TARGET)],
        capture_output=True, encoding="utf-8", errors="replace",
    )

    print(f"returncode: {proc.returncode}")
    print(f"\n=== stdout (있다면 앞부분 500자) ===")
    print(proc.stdout[:500] if proc.stdout else "(비어있음)")

    print(f"\n=== stderr (전체 traceback) ===")
    print(proc.stderr if proc.stderr else "(비어있음)")

    out_path = OUTPUT_DIR / "afsis_hwp5txt_stderr.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(proc.stderr or "(stderr 없음)", encoding="utf-8")
    print(f"\nstderr 전체를 파일로도 저장함(콘솔에서 위쪽이 스크롤로 잘렸으면 이 파일을 열어봐): {out_path}")


if __name__ == "__main__":
    main()
