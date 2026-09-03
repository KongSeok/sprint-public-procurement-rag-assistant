"""전역 경로/설정."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CSV_PATH = DATA_DIR / "data_list.csv"
RAW_FILES_DIR = DATA_DIR / "files"  # 원본 hwp/pdf 저장 위치. 폴더 연결 전에는 비어 있을 수 있음.
OUTPUT_DIR = BASE_DIR / "output"
CHROMA_DIR = OUTPUT_DIR / "chroma_db"

# 중간 단계 캐시 파일. 원본 hwp/pdf 재파싱(merge_text)은 문서 수가 많으면 시간이
# 걸리므로, 한 번 처리한 결과를 저장해뒀다가 다음 단계(chunking/indexing)에서
# 재사용한다. files/ 폴더 내용을 바꿨을 때는 이 캐시를 지우고 다시 만들어야 한다.
MERGED_DOCS_PATH = OUTPUT_DIR / "merged_docs.pkl"
CHUNKS_PATH = OUTPUT_DIR / "chunks.pkl"

# 문서 유형 분류 임계값 (텍스트 길이 기준, 1차 근사치)
SCAN_OR_TABLE_SUSPECT_LEN = 300
SHORT_TEXT_LEN = 1000

# Chunking 설정
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
PARENT_CHUNK_SIZE = 2400
PARENT_CHUNK_OVERLAP = 200

# 임베딩 모델. nlpai-lab/KURE-v1은 BAAI/bge-m3를 한국어 검색 데이터로 추가
# 파인튜닝한 모델(고려대 NLP&AI Lab, MIT 라이선스)로, 크기/속도는 bge-m3와
# 동일(0.6B params, dim=1024, ~2.2GB)하면서 한국어 검색 벤치마크에서 더 나은
# 성능을 보고하고 있어 bge-m3 대신 채택. bge-m3 기반이라 최대 8192 토큰까지
# 지원해서(참고: intfloat 계열 e5 모델은 보통 512 토큰 제한) 긴 Parent chunk도
# 잘리지 않는다.
EMBEDDING_MODEL_NAME = "nlpai-lab/KURE-v1"

# Golden Test Set (평가용 질문-정답 세트) 관련 경로.
# [2026-08-27 변경] 기존 CSV(id,query,expected_doc_id,난이도,담당자,note) 대신
# 팀 표준 JSON 포맷(번호/난이도/질문/정답_파일명 배열/비고)으로 바꿨다 - 정답이
# 여러 문서인 필터형 질문(예: "예산 1억 이상인 사업 전부")을 배열로 자연스럽게
# 표현하려면 CSV의 "|"로 구분한 문자열보다 JSON 배열이 더 안전하다(구분자 충돌
# 위험이 없음). src/evaluation.py의 load_golden_set()이 이 JSON을 읽어 기존
# 내부 컬럼명(id/query/expected_doc_id/난이도)으로 정규화한다.
# [2026-08-31 변경] 개인 25개(golden_set.json) 대신 팀원이 취합/검증한 전체
# 111개짜리 세트(golden_testset_verified_111_v6.json)로 교체 - data/ 폴더에
# 같은 팀 표준 포맷으로 들어있다는 전제. 담당자 컬럼이 여러 명으로 채워져
# 있으면 step5_evaluate.py가 자동으로 팀 전체/담당자별 현황으로 전환된다.
GOLDEN_SET_PATH = DATA_DIR / "golden_testset_verified_111_v6.json"
EVAL_RESULTS_PATH = OUTPUT_DIR / "eval_results.csv"

# 사업 금액 결측/0원 건 중 본문에서 후보 금액을 찾았지만 자동 채택은 위험한
# 경우(예: 총액/분납 이중집계 가능성)를 팀원이 직접 확인해 확정한 값을 넣어두는
# 수동 검수 파일. 파일이 없으면 그냥 건너뛴다 -> 처음엔 없어도 정상 동작함.
BUDGET_OVERRIDES_PATH = DATA_DIR / "budget_overrides.csv"

# 입찰 참여 마감일도 예산과 같은 이유로 자동 확정하지 않고 후보 스니펫만
# 노출한다(load_metadata.resolve_deadline_from_text 문서화 참고). 사람이 그
# 후보를 확인해 실제 날짜를 확정하면 이 파일에 적어서 반영한다 - 예전엔 이
# 파일이 없어서, 사람이 마감일 후보를 확인해도 그 결과가 실제로 chunking
# 단계까지 전달될 방법이 없었다(2026-08-27에 발견되어 추가).
DEADLINE_OVERRIDES_PATH = DATA_DIR / "deadline_overrides.csv"

# [2026-08-28 추가] 데이터 수집 단계에서 같은 공고가 서로 다른 발주기관
# 이름(게시 채널/브랜드명)으로 중복 수집된 건을 제외하는 파일. 예전에는
# check_duplicate_titles()가 "제목만 같고 doc_id/발주기관이 다르니 별개
# 문서"라고 판단했는데, 이는 필드값만 비교한 성급한 결론이었다 - 실제로
# 본문 텍스트를 비교해보니 두 쌍(의료기기산업 종합정보시스템, 통합정보시스템
# 고도화 용역) 모두 짧은 쪽 문서 전체가 긴 쪽 문서 안에 글자 그대로 100%
# 포함돼 있었고(shingle 기반 포함률 1.000), 심지어 "다른 발주기관"으로
# 표시된 문서 본문 안에 진짜 발주기관 이름이 그대로 적혀 있었다(예:
# "국가과학기술지식정보서비스"로 표시된 문서 첫 줄에 "본 자료는 한국한의학
# 연구원 제안서 작성 이외의 목적으로... 금함"). 즉 발주기관 필드가 실제
# 발주기관이 아니라 게시 채널/포털 이름을 잘못 담고 있던 데이터 수집 오류로
# 판단, 공고번호가 있는(=행정적으로 확인 가능한) 쪽만 정본으로 남기고
# 나머지는 제외한다. 컬럼: doc_id(제외할 문서), dup_of(정본 문서),
# reason(제외 근거). 파일이 없으면 그냥 건너뛴다.
DUPLICATE_EXCLUSIONS_PATH = DATA_DIR / "duplicate_exclusions.csv"
