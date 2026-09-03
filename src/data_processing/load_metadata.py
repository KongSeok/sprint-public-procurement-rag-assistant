"""1단계: 원본 로드 / 4단계: 메타데이터 정제.

data_list.csv를 읽어 각 문서에 대해:
  - doc_id를 파일명 기준으로 부여 (공고 번호는 18건 결측이라 기본 키로 부적합)
  - 사업 금액 0원/결측을 budget_unknown 플래그로 구분하고, 본문에서 후보 금액을
    찾아 사람이 검수할 수 있게 노출한다(자동으로 값을 확정하진 않음 - 이유는
    아래 _extract_budget_candidate 문서화 참고).
  - 날짜 컬럼 파싱. 마감일은 본문에도 근거가 없어 결측 플래그만 남기고,
    시작일은 공개일자로부터 근사 추정(추정 여부 플래그 포함)한다.
  - 사업명의 대괄호 태그([사전공개]/[긴급]/[재공고] 등)를 별도 컬럼으로 뽑아둔다
    - 결측 필드들이 이런 태그가 붙은 "아직 확정 전" 단계 공고에 몰려있는 경향이
    있어서, 결측을 채우기보다 "왜 결측인지" 설명하는 근거로 유용하다.

각 결측 컬럼의 처리 방침(왜 이렇게 했는지):

1. 사업 금액(7건 0/결측) - 자동으로 숫자를 채우지 않는다. 실제로 본문 정규식
   추출을 테스트해보니, 어떤 문서(경희대)는 "총 400,000,000원 - 1차년도
   200,000,000원 - 2차년도 200,000,000원" 처럼 총액과 분납액이 같이 나와서
   본문에 있는 금액을 전부 더하면 800,000,000원으로 2배 뻥튀기되는 반면, 다른
   문서(한국철도공사 모바일오피스)는 "개발비 359백만원 + H/W 484백만원"처럼
   진짜 더해야 맞는 금액이 나온다. 정규식만으로는 이 둘을 구분할 수 없어서,
   자동으로 값을 확정하면 조용히 틀린 숫자가 예산 필터/추천 기능에 들어갈
   위험이 있다. 그래서 "본문에 후보 금액이 있다"는 것까지만 자동 탐지하고
   (사업_금액_후보텍스트 컬럼), 실제 확정은 사람이 BUDGET_OVERRIDES_PATH
   파일에 적어서 반영하는 구조로 뒀다. "비공개"라고 명시된 경우(을지대학교
   등)는 사람이 볼 필요도 없이 명확하므로 undisclosed로 자동 구분한다. 참고로
   전체 100건의 사업 금액이 5,500만원~50억원까지 폭이 커서, 평균/중앙값으로
   채우는 건 오히려 없는 신뢰도를 만들어내는 것이라 하지 않는다.
   추가로 중요한 점: clean_metadata()가 이 판단을 할 때 쓰는 텍스트는 아직
   CSV의 1차 추출본(`텍스트` 컬럼)뿐이다 - 이 컬럼은 표/스캔본 위주 문서에서
   품질이 낮다고 이미 확인됐기 때문에, "CSV 텍스트에 없다"가 "실제 문서에도
   없다"를 보장하지 않는다. 그래서 원본을 재파싱한 뒤의 최종 판단은 이 함수가
   아니라 merge_text 단계의 resolve_budget_from_text()에서 다시 이뤄진다 -
   merge_text.merge_all()이 만든(또는 output/merged_docs.pkl 캐시를 불러올 때
   자동으로 재적용되는) 최종 본문(text 컬럼)을 기준으로 재평가해, 재파싱으로
   원본 표/본문을 제대로 읽었을 때만 드러나는 예산 정보를 놓치지 않는다.
2. 입찰 참여 마감일(8건 결측) - 처음엔 CSV의 1차 추출 텍스트만 보고 "본문에도
   근거 없음"이라 판단했는데, 이건 성급한 결론이었다. CSV 텍스트는 표/스캔본
   위주 문서에서 품질이 낮다고 이미 확인된 컬럼이라, "CSV 텍스트에 없다"가
   "실제 문서에도 없다"를 보장하지 않는다(1번 사업 금액에서 겪은 것과 동일한
   문제). 그래서 원본 재파싱까지 반영한 최종 판단은 merge_text 단계의
   resolve_deadline_from_text()로 옮겼다 - CSV 텍스트가 아니라 merge_text가
   만든 최종 본문(원본 재파싱 성공 시 그 결과)을 기준으로 다시 검사하고,
   결과를 입찰참여마감일_출처(candidate/announced_later/no_info)와
   입찰참여마감일_후보텍스트로 노출한다. 사업 금액과 마찬가지로 날짜도
   자동으로 확정하지 않고 스니펫만 보여줘서 사람이 확인하게 한다. 참고로 이
   8건 중 절반이 [사전공개]/[긴급]/[국제] 같은 태그가 붙어있어(전체 평균
   17%보다 높음), "아직 마감일이 정해지지 않은 초기 단계 공고"일 가능성이
   있다는 근거로 사업명_태그 컬럼을 같이 남겨둔다.
3. 입찰 참여 시작일(26건 결측) - 공개일자와 시작일이 둘 다 있는 74건을 분석하니
   47%가 갭 0일(당일 시작), 중앙값 2일로 "공고 나오면 거의 바로 참여 가능"이
   일반적 패턴이었다. 그래서 결측이면 공개일자로 근사 대체하되, 반드시
   입찰참여시작일_추정 플래그를 남겨 실측값과 구분한다 - LLM이 이 값을 근거로
   답할 때 "본문에 명시된 값이 아니라 공개일 기준 추정"이라고 밝힐 수 있어야
   hallucination을 피할 수 있다.
4. 공고 번호/공고 차수(18건 결측) - doc_id는 이미 파일명을 쓰고 있어서 실질적
   영향이 없다. 채울 방법도 마땅치 않아(행정 식별자라 본문에서 복구 불가) 그대로
   결측 플래그만 남긴다.
"""
from __future__ import annotations

import re

import pandas as pd

from ..config import BUDGET_OVERRIDES_PATH, CSV_PATH, DEADLINE_OVERRIDES_PATH, DUPLICATE_EXCLUSIONS_PATH

REQUIRED_COLUMNS = [
    "공고 번호", "공고 차수", "사업명", "사업 금액", "발주 기관",
    "공개 일자", "입찰 참여 시작일", "입찰 참여 마감일", "사업 요약",
    "파일형식", "파일명", "텍스트",
]

_BUDGET_KEYWORDS = ["사업예산", "사업 금액", "사업금액", "사업비", "추정가격"]
_MONEY_RE = re.compile(r"[\d,]+\s*(?:억|천만|백만|만)?\s*원")


def _extract_budget_candidate(text: str) -> tuple[str, str | None]:
    """본문에서 예산 관련 후보를 찾는다. 절대 숫자를 자동으로 합산/확정하지
    않는다 - docstring 1번 참고(총액+분납액을 잘못 더할 위험). 반환값은
    (분류, 스니펫) 튜플:
      - ("undisclosed", None): "비공개"가 명시된 경우
      - ("candidate", "...원 근처 본문 스니펫..."): 원 단위 금액 표현이 있는 경우,
        사람이 읽고 BUDGET_OVERRIDES_PATH에 확정값을 적어 넣도록 스니펫만 제공
      - ("no_info", None): 본문 어디에도 예산 관련 실제 금액이 없는 경우
    """
    if not isinstance(text, str):
        return "no_info", None
    for kw in _BUDGET_KEYWORDS:
        for m in re.finditer(re.escape(kw), text):
            window = text[m.end(): m.end() + 150]
            if "비공개" in window or "공개하지" in window or "포함되지 않" in window or "미포함" in window:
                return "undisclosed", None
            if _MONEY_RE.search(window):
                snippet = (kw + window[:100]).replace("\n", " ").replace("\r", " ").strip()
                return "candidate", snippet
    return "no_info", None


_DEADLINE_KEYWORDS = ["마감일시", "마감 일시", "입찰 마감", "제출 마감", "접수 마감", "마감일", "마감"]
_DATE_RE = re.compile(r"\d{4}\s*[.\-]\s*\d{1,2}\s*[.\-]\s*\d{1,2}|\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일")


def _extract_deadline_candidate(text: str) -> tuple[str, str | None]:
    """본문에서 마감일 관련 후보를 찾는다(사업 금액과 같은 이유로 숫자/날짜를
    자동 확정하지 않고 스니펫만 노출). 반환값은 (분류, 스니펫):
      - ("announced_later", None): "추후 공지"/"별도 공지" 등 아직 미정임을 명시
      - ("candidate", "..."): 날짜 형태가 근처에 있는 경우, 사람이 확인하도록 스니펫 제공
      - ("no_info", None): 본문 어디에도 마감 관련 날짜가 없는 경우
    """
    if not isinstance(text, str):
        return "no_info", None
    for kw in _DEADLINE_KEYWORDS:
        for m in re.finditer(re.escape(kw), text):
            window = text[max(0, m.start() - 10): m.end() + 80]
            if "추후" in window or ("별도" in window and "공지" in window):
                return "announced_later", None
            if _DATE_RE.search(window):
                snippet = window.replace("\n", " ").replace("\r", " ").strip()
                return "candidate", snippet
    return "no_info", None


def resolve_deadline_from_text(df: pd.DataFrame, text_col: str = "text") -> pd.DataFrame:
    """resolve_budget_from_text와 같은 이유로, 마감일 결측도 CSV 1차 추출
    텍스트가 아니라 merge_text가 만든 최종 본문(text_col) 기준으로 재평가한다.
    입찰참여마감일_결측(원본 날짜 컬럼 자체의 결측 여부)은 그대로 두고,
    입찰참여마감일_출처/후보텍스트만 갱신한다. 이미 manual_confirmed된 행은
    (사업 금액과 동일하게) 후보 재탐색으로 덮어쓰지 않는다."""
    df = df.copy()
    if "입찰참여마감일_출처" not in df.columns:
        df["입찰참여마감일_출처"] = None
    if "입찰참여마감일_후보텍스트" not in df.columns:
        df["입찰참여마감일_후보텍스트"] = None
    if "입찰참여마감일_정제" not in df.columns:
        # 옛날 캐시(output/merged_docs.pkl)에는 이 컬럼이 없을 수 있어 안전하게 초기화.
        df["입찰참여마감일_정제"] = df["입찰 참여 마감일_dt"] if "입찰 참여 마감일_dt" in df.columns else pd.NaT
    target = df.index[df["입찰참여마감일_결측"] & (df["입찰참여마감일_출처"] != "manual_confirmed")]
    for idx in target:
        source, snippet = _extract_deadline_candidate(df.at[idx, text_col])
        df.at[idx, "입찰참여마감일_출처"] = source
        df.at[idx, "입찰참여마감일_후보텍스트"] = snippet if source == "candidate" else None
    return _apply_deadline_overrides(df)


_TAG_RE = re.compile(r"\[([^\[\]]+)\]")


def _extract_name_tags(name: str) -> str:
    """사업명의 대괄호 태그([사전공개]/[긴급]/[재공고] 등)를 콤마로 이어붙여 반환."""
    if not isinstance(name, str):
        return ""
    return ",".join(_TAG_RE.findall(name))


def _load_duplicate_exclusions(path=DUPLICATE_EXCLUSIONS_PATH) -> pd.DataFrame | None:
    """같은 공고가 중복 수집된 것으로 확인돼 코퍼스에서 제외하기로 한 문서
    목록. 컬럼: doc_id(제외할 파일명), dup_of(정본 파일명), reason(제외 근거).
    파일이 없으면 그냥 건너뛴다(처음엔 없어도 정상 동작). config.py의
    DUPLICATE_EXCLUSIONS_PATH 문서화 참고."""
    if not path.exists():
        return None
    exclusions = pd.read_csv(path)
    required = {"doc_id", "dup_of", "reason"}
    missing = required - set(exclusions.columns)
    if missing:
        raise ValueError(f"duplicate_exclusions.csv에 필요한 컬럼이 없습니다: {missing}")
    return exclusions


def _apply_duplicate_exclusions(df: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    """data_list.csv를 막 읽은 원본 df(아직 doc_id 컬럼 없음, 파일명 컬럼만 있음)
    에서 duplicate_exclusions.csv에 적힌 파일명 행을 제거한다. load_raw_csv()
    맨 끝에서 호출해서, 이후 단계(clean_metadata/merge_text/chunking/indexing/
    evaluation) 전부가 애초에 이 문서들을 본 적이 없는 것처럼 동작하게 한다."""
    exclusions = _load_duplicate_exclusions()
    if exclusions is None:
        return df
    to_drop = set(exclusions["doc_id"])
    mask = df["파일명"].isin(to_drop)
    if verbose and mask.any():
        for _, r in exclusions.iterrows():
            if r["doc_id"] in set(df.loc[mask, "파일명"]):
                print(f"[load_metadata] 중복 제외: {r['doc_id']!r} (정본: {r['dup_of']!r})")
    return df.loc[~mask].reset_index(drop=True)


def load_raw_csv(csv_path=CSV_PATH) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV에 예상 컬럼이 없습니다: {missing}")
    df = _apply_duplicate_exclusions(df)
    return df


_PAREN_RE = re.compile(r"\([^)]*\)")
_BRACKET_RE = re.compile(r"\[[^\]]*\]")


def _normalize_title(name: str) -> str:
    """사업명에서 괄호/대괄호 부가정보(예: "(2차)", "(재공고)", "[긴급]")를
    지워서 "같은 사업의 차수/재공고 차이만 있는 제목"을 하나로 묶는다."""
    if not isinstance(name, str):
        return ""
    name = _PAREN_RE.sub("", name)
    name = _BRACKET_RE.sub("", name)
    return re.sub(r"\s+", " ", name).strip()


def check_duplicate_titles(df: pd.DataFrame) -> pd.DataFrame:
    """사업명이 같거나(괄호/대괄호 제거 후) 비슷한 행이 여러 개 있으면 경고용으로
    뽑아둔다.

    [2026-08-28 정정] 예전 버전의 이 docstring은 "통합정보시스템 고도화
    용역"(국가과학기술지식정보서비스 vs 한국한의학연구원)과 "의료기기산업
    종합정보시스템(정보관리기관) 기능개선 사업" vs "...기능개선 사업(2차)"
    (한국보건산업진흥원 vs BioIN)을 "제목만 같고 doc_id/발주기관은 다르니
    실제로는 서로 다른 별개 문서"라고 결론 냈었다 - 그런데 이건 필드값(doc_id,
    발주기관)만 비교하고 본문 텍스트는 확인하지 않은 성급한 판단이었다.
    실제로 본문을 비교해보니 두 쌍 모두 짧은 쪽 문서의 텍스트가 긴 쪽 문서
    안에 글자 그대로 100% 포함돼 있었고(shingle 기반 포함률 1.000), 심지어
    "국가과학기술지식정보서비스"로 표시된 문서는 본문 첫 줄에 스스로 "본
    자료는 한국한의학연구원 제안서 작성 이외의 목적으로... 금함"이라고 적혀
    있어 발주기관 필드 자체가 실제 발주기관이 아니라 데이터 수집 시 잘못
    들어간 게시 채널/포털 이름이었음이 확인됐다. 즉 이 두 쌍은 "제목이 같은
    다른 문서"가 아니라 "같은 공고가 두 번 수집된 데이터 중복"이었다 - 정정된
    처리는 DUPLICATE_EXCLUSIONS_PATH(data/duplicate_exclusions.csv,
    load_raw_csv()/load_merged()에서 자동 적용)를 참고.

    이 함수 자체는 여전히 유효하다 - "제목이 비슷한 행이 여럿 있다"는 신호를
    자동으로 표시해주는 역할이고, 그게 진짜 중복인지 아니면 우연히 제목만
    겹치는 별개 문서인지는 위 사례처럼 본문까지 비교해서 사람이 최종 판단해야
    한다(제목 일치만으로 자동 병합/제외하면 안 됨 - 진짜 별개 문서일 수도
    있으니까). "(2차)" 같은 괄호가 붙어 원본 사업명 문자열 자체는 다른 경우까지
    잡으려고 괄호/대괄호를 지운 정규화 제목(_normalize_title)으로 비교한다.
    doc_id/발주기관까지 완전히 같은 완전 중복 행이 있다면 그건 진짜 데이터
    오류이므로 별도로 표시한다."""
    df = df.copy()
    df["_사업명_정규화"] = df["사업명"].apply(_normalize_title)
    dup_title = df[df.duplicated(subset=["_사업명_정규화"], keep=False)].copy()
    if dup_title.empty:
        return dup_title.assign(is_true_duplicate=pd.Series(dtype=bool))
    dup_title["is_true_duplicate"] = dup_title.duplicated(
        subset=["_사업명_정규화", "발주 기관"], keep=False
    )
    cols = ["doc_id", "사업명", "발주 기관", "is_true_duplicate", "_사업명_정규화"]
    return dup_title[cols].sort_values(["_사업명_정규화", "doc_id"])


def _load_budget_overrides(path=BUDGET_OVERRIDES_PATH) -> pd.DataFrame | None:
    """팀원이 후보 스니펫을 확인하고 직접 확정한 예산값 파일.
    컬럼: doc_id, 확정_사업금액. 파일이 없으면 그냥 건너뛴다(처음엔 없어도 됨)."""
    if not path.exists():
        return None
    overrides = pd.read_csv(path)
    required = {"doc_id", "확정_사업금액"}
    missing = required - set(overrides.columns)
    if missing:
        raise ValueError(f"budget_overrides.csv에 필요한 컬럼이 없습니다: {missing}")
    return overrides


def _apply_budget_overrides(df: pd.DataFrame) -> pd.DataFrame:
    overrides = _load_budget_overrides()
    if overrides is None:
        return df
    override_map = dict(zip(overrides["doc_id"], overrides["확정_사업금액"]))
    for idx in df.index:
        doc_id = df.at[idx, "doc_id"]
        if doc_id in override_map:
            df.at[idx, "사업_금액_정제"] = override_map[doc_id]
            df.at[idx, "사업_금액_출처"] = "manual_confirmed"
            df.at[idx, "budget_unknown"] = False
    return df


def _load_deadline_overrides(path=DEADLINE_OVERRIDES_PATH) -> pd.DataFrame | None:
    """사람이 마감일 후보 스니펫(입찰참여마감일_후보텍스트)을 확인하고 직접
    확정한 날짜를 적어두는 파일. 컬럼: doc_id, 확정_마감일(예: "2024-05-31" 또는
    "2024-05-31 11:00"). 파일이 없으면 그냥 건너뛴다 - 처음엔 없어도 정상 동작함.
    _apply_budget_overrides와 정확히 같은 구조 - 예전엔 이 마감일 쪽 파일/적용
    함수가 아예 없어서, 사람이 후보를 확인해도 그 결과를 실제로 반영할 방법이
    없었다(2026-08-27에 발견, budget과 대칭이 되도록 추가)."""
    if not path.exists():
        return None
    overrides = pd.read_csv(path)
    required = {"doc_id", "확정_마감일"}
    missing = required - set(overrides.columns)
    if missing:
        raise ValueError(f"deadline_overrides.csv에 필요한 컬럼이 없습니다: {missing}")
    return overrides


def _apply_deadline_overrides(df: pd.DataFrame) -> pd.DataFrame:
    overrides = _load_deadline_overrides()
    if overrides is None:
        return df
    override_map = dict(zip(overrides["doc_id"], overrides["확정_마감일"]))
    for idx in df.index:
        doc_id = df.at[idx, "doc_id"]
        if doc_id in override_map:
            df.at[idx, "입찰참여마감일_정제"] = pd.to_datetime(override_map[doc_id], errors="coerce")
            df.at[idx, "입찰참여마감일_출처"] = "manual_confirmed"
            df.at[idx, "입찰참여마감일_결측"] = False
    return df


def resolve_budget_from_text(df: pd.DataFrame, text_col: str = "text") -> pd.DataFrame:
    """merge_text.py가 만든 최종 본문(text_col)을 기준으로 예산 후보를 다시 평가한다.

    clean_metadata()는 아직 원본 파일을 재파싱하기 전이라 data_list.csv의 1차
    추출 텍스트(`텍스트` 컬럼)만 볼 수 있는데, 이 컬럼은 표/스캔본 위주 문서
    21건에서 특히 품질이 낮다고 이미 확인됐다. 즉 "CSV 텍스트에 없다"가 "실제
    문서에도 없다"를 보장하지 않는다 - 원본을 제대로 재파싱한 text_col(=merge_text
    가 만든 최종 text 컬럼, 재파싱 성공 시 그 결과·실패 시 CSV 폴백)을 봐야 진짜
    결측인지 판단할 수 있다. merge_text.merge_all()과 load_merged() 양쪽에서
    호출해서, 캐시된 output/merged_docs.pkl을 불러오기만 해도 (재파싱을 다시
    돌리지 않고도) 예산 후보가 최신 본문 기준으로 재평가되게 한다.
    이미 manual_confirmed된 행은 건드리지 않는다.
    """
    df = df.copy()
    target = df.index[df["budget_unknown"] & (df["사업_금액_출처"] != "manual_confirmed")]
    for idx in target:
        source, snippet = _extract_budget_candidate(df.at[idx, text_col])
        df.at[idx, "사업_금액_출처"] = source
        df.at[idx, "사업_금액_후보텍스트"] = snippet if source == "candidate" else None
    return _apply_budget_overrides(df)


def clean_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """메타데이터 정제 규칙 적용, doc_id 부여."""
    df = df.copy()

    # 문서 고유 ID: 파일명 사용 (100건 모두 유니크 확인됨)
    if df["파일명"].duplicated().any():
        dup = df.loc[df["파일명"].duplicated(keep=False), "파일명"].unique()
        raise ValueError(f"파일명 중복 발견, doc_id 정책 재검토 필요: {dup}")
    df["doc_id"] = df["파일명"]

    # 사업 금액: 0 또는 결측 -> budget_unknown 플래그.
    # 여기(clean_metadata)는 아직 원본 파일을 재파싱하기 전 단계라 CSV의 1차
    # 추출 텍스트(`텍스트` 컬럼)만 볼 수 있다 - 이 컬럼은 표/스캔본 위주 문서에서
    # 품질이 낮다고 이미 확인됐으므로, 후보 탐색은 잠정적인 초기값일 뿐이다.
    # 원본 재파싱까지 반영한 최종 판단은 merge_text.merge_all()/load_merged()가
    # 호출하는 resolve_budget_from_text()에서 이뤄진다(그게 진짜 결측인지 CSV
    # 추출 실패인지 구분해준다). 여기서는 원본이 아예 연결 안 된 상태에서도
    # 최소한의 초기값이 있도록만 채워둔다.
    # 0원뿐 아니라 1원처럼 "실제 금액일 수 없는" sentinel도 결측으로 취급한다.
    # (사단법인 보험개발원_실손보험 청구 전산화 시스템 구축 사업.hwp이 정확히
    # 이 케이스: CSV상 사업 금액=1이라 예전 코드(==0만 체크)는 놓쳤었다.)
    df["budget_unknown"] = df["사업 금액"].isna() | (df["사업 금액"] <= 1)
    df["사업_금액_정제"] = df["사업 금액"].where(~df["budget_unknown"])
    df["사업_금액_출처"] = df["budget_unknown"].map(lambda x: "csv" if not x else None)
    df["사업_금액_후보텍스트"] = None

    for idx in df.index[df["budget_unknown"]]:
        source, snippet = _extract_budget_candidate(df.at[idx, "텍스트"])
        df.at[idx, "사업_금액_출처"] = source
        if source == "candidate":
            df.at[idx, "사업_금액_후보텍스트"] = snippet

    # 사람이 검수해서 확정한 값이 있으면 반영 (파일 없으면 스킵)
    df = _apply_budget_overrides(df)

    # 날짜 파싱 (실패해도 NaT로 두고 진행)
    for col in ["공개 일자", "입찰 참여 시작일", "입찰 참여 마감일"]:
        df[col + "_dt"] = pd.to_datetime(df[col], errors="coerce")

    # 입찰 참여 시작일 결측 -> 공개일자로 근사 대체 (반드시 추정 플래그와 함께).
    # 근거: 공개일자/시작일이 둘 다 있는 74건 중 47%가 갭 0일, 중앙값 2일이라
    # "공고 나오면 거의 바로 참여 가능"이 일반적 패턴.
    df["입찰참여시작일_추정"] = df["입찰 참여 시작일_dt"].isna() & df["공개 일자_dt"].notna()
    df.loc[df["입찰참여시작일_추정"], "입찰 참여 시작일_dt"] = df.loc[
        df["입찰참여시작일_추정"], "공개 일자_dt"
    ]

    # 입찰 참여 마감일 결측: 본문에도 근거가 없어 채우지 않고 플래그만 남김.
    # 사업 금액과 대칭되게, 사람이 확정한 값이 있으면 반영할 수 있도록
    # 입찰참여마감일_정제(최종적으로 chunking이 참조할 값)를 여기서도 만든다 -
    # 기본값은 CSV에 이미 있던 날짜(결측이면 NaT), 사람이 deadline_overrides.csv에
    # 확정값을 적으면 그걸로 덮어쓴다.
    df["입찰참여마감일_결측"] = df["입찰 참여 마감일_dt"].isna()
    df["입찰참여마감일_정제"] = df["입찰 참여 마감일_dt"]
    df["입찰참여마감일_출처"] = df["입찰참여마감일_결측"].map(lambda x: "csv" if not x else None)
    df["입찰참여마감일_후보텍스트"] = None
    df = _apply_deadline_overrides(df)

    # 공고 번호 결측 플래그 (사전공개/재공고 등 정식 공고번호 미부여 케이스로 추정)
    df["공고번호_결측"] = df["공고 번호"].isna()

    # 사업명 대괄호 태그([사전공개]/[긴급]/[재공고]/[협상형]/[국제] 등)
    # - 결측 필드들이 이런 태그 붙은 공고에 몰리는 경향이 있어 결측 이유를
    #   설명하는 데 참고할 수 있다.
    df["사업명_태그"] = df["사업명"].apply(_extract_name_tags)

    return df


def load_clean_metadata(csv_path=CSV_PATH) -> pd.DataFrame:
    return clean_metadata(load_raw_csv(csv_path))


if __name__ == "__main__":
    df = load_clean_metadata()
    print(f"총 {len(df)}건 로드")
    print("budget_unknown 건수:", df["budget_unknown"].sum())
    print("  사업_금액_출처 분포:")
    print(df.loc[df["사업_금액_출처"].notna(), "사업_금액_출처"].value_counts().to_string())
    print("입찰참여시작일_추정 건수:", df["입찰참여시작일_추정"].sum())
    print("입찰참여마감일_결측 건수:", df["입찰참여마감일_결측"].sum())
    print("공고번호_결측 건수:", df["공고번호_결측"].sum())
    print()
    cand = df[df["사업_금액_출처"] == "candidate"][["doc_id", "사업_금액_후보텍스트"]]
    if len(cand):
        print("=== 사람 검수가 필요한 예산 후보 (data/budget_overrides.csv에 확정값 기입) ===")
        for _, r in cand.iterrows():
            print(f"- {r['doc_id']}\n    {r['사업_금액_후보텍스트']}")
