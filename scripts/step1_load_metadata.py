"""1단계: 메타데이터 로드/정제 확인용. 파이참에서 그냥 우클릭 > Run 하면 됩니다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_processing.load_metadata import load_clean_metadata  # noqa: E402

if __name__ == "__main__":
    df = load_clean_metadata()
    print(f"총 {len(df)}건 로드")
    print("budget_unknown(예산 0원/결측) 건수:", df["budget_unknown"].sum())
    print("공고번호_결측 건수:", df["공고번호_결측"].sum())
    print()
    print(df[["doc_id", "파일형식", "budget_unknown", "공고번호_결측"]].head(10))
