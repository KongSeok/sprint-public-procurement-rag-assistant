"""2~3단계: 원본 재파싱/CSV 폴백, 문서유형 분류 확인용. 파이참에서 우클릭 > Run.

결과를 output/merged_docs.pkl에 저장해서, 다음 단계(step3/step4)에서 다시
100건을 처음부터 재파싱하지 않고 이 캐시를 재사용하게 한다. files/ 폴더의
원본 파일을 바꿨다면 이 스크립트를 다시 실행해서 캐시를 갱신해야 한다.

이 스크립트가 하는 검증(중요 - "재파싱해서 결측/문제점이 확인되는지" 보는 곳):
  1. 예산/마감일 결측을 CSV 1차 추출 텍스트 기준(재파싱 전)과 원본 재파싱
     결과 기준(재파싱 후)으로 각각 평가해서, 재파싱으로 상태가 바뀐(=CSV에는
     없었지만 원본을 제대로 읽으니 나온) 문서를 따로 보여준다. `data/files/`에
     원본이 없으면(=CSV 텍스트만 있으면) 재파싱 전/후가 같아서 "바뀐 문서 없음"
     으로 나온다 - 이건 정상이다.
  2. 사업명이 같은데 파일명/발주기관이 다른 행("제목은 같지만 실제로는 다른
     문서")을 경고로 보여준다. 팀원의 결측치 정정 리포트가 이런 케이스를
     "발주기관 오매핑"으로 잘못 정정한 적이 있어서(실제로는 서로 다른 두 RFP를
     하나로 착각) 추가했다.
  3. output/missing_data_report.csv를 재파싱 결과 기준으로 매번 새로 만든다
     (전에는 별도로 손으로 만들었는데, 이제 이 스크립트를 돌릴 때마다 최신
     상태로 자동 갱신된다).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from src.data_processing.load_metadata import (  # noqa: E402
    check_duplicate_titles,
    load_clean_metadata,
    resolve_deadline_from_text,
)
from src.data_processing.merge_text import load_merged, merge_all, save_merged  # noqa: E402

if __name__ == "__main__":
    df = load_clean_metadata()

    # 재파싱 전(before) 스냅샷: CSV 1차 추출 텍스트만 봤을 때의 판단.
    # 예산(사업_금액_출처)은 clean_metadata()가 이미 `텍스트` 컬럼으로 계산해뒀고,
    # 마감일은 여기서 같은 함수를 `텍스트` 컬럼에 대해 한 번 더 돌려서 만든다
    # (merge_all() 안에서는 재파싱된 `text` 컬럼에 대해 다시 계산됨).
    before_budget = df.set_index("doc_id")["사업_금액_출처"].copy()
    before_deadline_df = resolve_deadline_from_text(df, text_col="텍스트")
    before_deadline = before_deadline_df.set_index("doc_id")["입찰참여마감일_출처"].copy()

    result = merge_all(df)
    save_merged(result)
    # 저장 직후 다시 불러온다 - load_merged()는 불러올 때마다
    # resolve_budget_from_text/resolve_deadline_from_text를 다시 적용하도록
    # 만들어둔 "자가 치유" 함수라(merge_text.py의 load_merged 문서화 참고),
    # 어떤 이유로든 merge_all()이 리턴한 result에 예산/마감일 재평가 컬럼이
    # 아직 안 실려 있었더라도 여기서 확실히 채워진 버전을 쓰게 된다.
    result = load_merged()

    print()
    print("source 분포 (raw_parsed = 원본 재파싱 채택, csv_fallback = CSV 텍스트 사용):")
    print(result["source"].value_counts())
    print()
    print("doc_type 분포:")
    print(result["doc_type"].value_counts())

    fallback = result[result["source"] == "csv_fallback"]
    if len(fallback) > 0:
        print()
        print(f"csv_fallback {len(fallback)}건 상세 (왜 원본 재파싱을 못 썼는지):")
        for _, row in fallback.iterrows():
            print(f"  - [{row['파일형식']}] {row['파일명']}")
            print(f"    사유: {row['parse_note']}")
    print()
    print("표(table)가 1개 이상 추출된 문서 수:", (result["n_tables"] > 0).sum())

    def _changed_mask(before: pd.Series, after: pd.Series) -> pd.Series:
        """pandas의 `!=`는 None/NaN끼리 비교해도 True를 반환하는 함정이 있어서
        (예: pd.Series([None]) != pd.Series([None]) -> True), 둘 다 결측이면
        "안 바뀜"으로 처리하도록 직접 판단한다."""
        before = before.reindex(after.index)
        both_null = before.isna() & after.isna()
        return (before != after) & ~both_null

    # === 재파싱 전/후 비교: 원본을 제대로 읽어서 새로 확인된 것이 있는지 ===
    print()
    print("=== 재파싱 전(CSV 텍스트) vs 후(원본 재파싱) 비교 ===")
    if "사업_금액_출처" not in result.columns:
        print("!! result에 사업_금액_출처 컬럼이 없음 - resolve_budget_from_text가 반영 안 된 상태.")
        print("   src/merge_text.py, src/load_metadata.py가 최신본인지 확인하고 __pycache__ 지운 뒤 다시 실행해줘.")
    else:
        after_budget = result.set_index("doc_id")["사업_금액_출처"]
        budget_changed = result.set_index("doc_id").loc[_changed_mask(before_budget, after_budget)]
        if len(budget_changed):
            print(f"예산 판단이 재파싱으로 바뀐 문서 {len(budget_changed)}건:")
            for doc_id, row in budget_changed.iterrows():
                before = before_budget.get(doc_id)
                print(f"  - {doc_id}: {before} -> {row['사업_금액_출처']}")
                if row["사업_금액_출처"] == "candidate":
                    print(f"      후보: {row['사업_금액_후보텍스트']}")
        else:
            print("예산 판단이 재파싱으로 바뀐 문서 없음 (원본 파일이 아직 없거나, CSV 텍스트와 동일한 정보만 있음)")

    if "입찰참여마감일_출처" not in result.columns:
        print("!! result에 입찰참여마감일_출처 컬럼이 없음 - resolve_deadline_from_text가 반영 안 된 상태.")
        print("   src/merge_text.py, src/load_metadata.py가 최신본인지 확인하고 __pycache__ 지운 뒤 다시 실행해줘.")
    else:
        after_deadline = result.set_index("doc_id")["입찰참여마감일_출처"]
        deadline_join = result.set_index("doc_id")
        deadline_changed = deadline_join.loc[_changed_mask(before_deadline, after_deadline)]
        if len(deadline_changed):
            print(f"\n마감일 판단이 재파싱으로 바뀐 문서 {len(deadline_changed)}건:")
            for doc_id, row in deadline_changed.iterrows():
                before = before_deadline.get(doc_id)
                print(f"  - {doc_id}: {before} -> {row['입찰참여마감일_출처']}")
                if row["입찰참여마감일_출처"] == "candidate":
                    print(f"      후보: {row['입찰참여마감일_후보텍스트']}")
        else:
            print("마감일 판단이 재파싱으로 바뀐 문서 없음 (원본 파일이 아직 없거나, CSV 텍스트와 동일한 정보만 있음)")

    # 예산/마감일 결측 재평가 결과 (재파싱 반영 후 최종 상태)
    print()
    print("=== 예산 결측 (재파싱 반영 후 최종) ===")
    print(result.loc[result["budget_unknown"], "사업_금액_출처"].value_counts().to_string())
    cand = result[result["사업_금액_출처"] == "candidate"][["doc_id", "사업_금액_후보텍스트"]]
    if len(cand):
        print(f"\n사람 검수가 필요한 예산 후보 {len(cand)}건 (data/budget_overrides.csv에 확정값 기입):")
        for _, r in cand.iterrows():
            print(f"  - {r['doc_id']}\n      {r['사업_금액_후보텍스트']}")

    print()
    print("=== 마감일 결측 (재파싱 반영 후 최종) ===")
    print(result.loc[result["입찰참여마감일_결측"], "입찰참여마감일_출처"].value_counts().to_string())
    dcand = result[result["입찰참여마감일_출처"] == "candidate"][
        ["doc_id", "입찰참여마감일_후보텍스트"]
    ]
    if len(dcand):
        print(f"\n사람 검수가 필요한 마감일 후보 {len(dcand)}건:")
        for _, r in dcand.iterrows():
            print(f"  - {r['doc_id']}\n      {r['입찰참여마감일_후보텍스트']}")

    # === 제목은 같은데 실제로는 다른 문서 경고 (발주기관 오매핑 오판 방지) ===
    print()
    print("=== 사업명 중복 경고 (제목이 같은 행들 - 발주기관까지 같아야 진짜 중복) ===")
    dup = check_duplicate_titles(result)
    if len(dup):
        for norm_name, group in dup.groupby("_사업명_정규화"):
            true_dup = group["is_true_duplicate"].any()
            tag = "!! 진짜 중복(파일명+발주기관까지 동일) - 데이터 확인 필요" if true_dup else "OK 제목만 같은/비슷한 별개 문서 (병합 금지)"
            print(f"  [{tag}] {norm_name}")
            for _, r in group.iterrows():
                print(f"      - {r['doc_id']} (사업명: {r['사업명']} / 발주기관: {r['발주 기관']})")
    else:
        print("사업명 중복 없음")

    # === 결측/이슈 리포트 재생성 (재파싱 결과 기준, 매번 최신화) ===
    report_cols = [
        "doc_id", "사업명_태그",
        "budget_unknown", "사업_금액_정제", "사업_금액_출처", "사업_금액_후보텍스트",
        "입찰참여시작일_추정", "입찰 참여 시작일_dt",
        "입찰참여마감일_결측", "입찰참여마감일_출처", "입찰참여마감일_후보텍스트",
        "공고번호_결측",
    ]
    report = result[report_cols].copy()
    has_issue = (
        report["budget_unknown"] | report["입찰참여시작일_추정"]
        | report["입찰참여마감일_결측"] | report["공고번호_결측"]
    )
    report = report[has_issue].copy()

    def _budget_resolution(row):
        if not row["budget_unknown"]:
            return ""
        return {
            "manual_confirmed": "해결됨(수동확정)",
            "undisclosed": "해결됨(비공개 확인)",
            "candidate": "검토 필요(후보 텍스트 있음)",
        }.get(row["사업_금액_출처"], "복구 불가(본문에도 정보 없음)")

    report["예산_처리상태"] = report.apply(_budget_resolution, axis=1)
    report_path = Path(__file__).resolve().parent.parent / "output" / "missing_data_report.csv"
    report.to_csv(report_path, index=False, encoding="utf-8-sig")
    print(f"\n결측/이슈 리포트 재생성됨({len(report)}건): {report_path}")

    # 재파싱된 텍스트를 눈으로 직접 확인할 수 있도록 엑셀에서 열리는 미리보기 CSV도 저장.
    # (output/merged_docs.pkl은 pandas로만 열리는 pickle이라 바로 눈으로 보기 어려움)
    preview_path = Path(__file__).resolve().parent.parent / "output" / "merged_docs_preview.csv"
    preview = result[["doc_id", "파일형식", "source", "doc_type", "n_tables", "parse_note"]].copy()
    preview["텍스트_길이"] = result["text"].str.len()
    preview["텍스트_미리보기"] = result["text"].str.slice(0, 300)
    preview.to_csv(preview_path, index=False, encoding="utf-8-sig")
    print(f"엑셀로 열어볼 수 있는 미리보기 저장: {preview_path}")
