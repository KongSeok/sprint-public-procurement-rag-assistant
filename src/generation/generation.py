"""Generation(답변 생성) 공통 로직 - gpt-5-mini 호출 + required_fact_groups
기반 Pass/Fail 채점. step6_generation_baseline.py(v6 golden set)와
step8_generation_golden_v3.py(golden-set-v3-share)가 이 모듈을 같이 쓴다
(원래 step6에 있던 걸 두 스크립트가 중복해서 들고 있지 않도록 이쪽으로
옮겼다 - 2026-09-01).

Generation 모델은 gpt-5-mini(OpenAI Responses API)를 쓴다 - 새 프로젝트에는
Chat Completions 대신 Responses API를 쓰라는 게 OpenAI 공식 권장사항이라
`client.responses.create()`로 호출했다.
(참고: https://developers.openai.com/api/docs/guides/migrate-to-responses ,
https://developers.openai.com/api/docs/quickstart)

[2026-09-02 저녁 추가] 팀원이 공유한 golden-set-v3-share 평가 인프라
(`fivecircles/architecture/specs/supplemental-evaluation-contract.md`)를
읽어보니, 우리가 지금까지 유일한 채점 기준으로 쓰던
`check_required_facts`(어휘 기반 문자열 매칭)를 팀원 쪽은 애초에
"참고용 diagnostic-only"로만 취급하고, 실제 정답성/충실도 판정은 LLM
검수(`gpt-5.6-sol`)로 한다 - 그리고 우리가 아예 재고 있지 않던 두 축을
따로 추적한다: required_doc_citation_coverage(답변이 실제로 필요한
문서를 인용했는지)와 abstention_behavior_match(정답 가능한 질문엔 답하고
불가능한 질문엔 기권하는지 골든셋 기대와 일치하는지). 이 두 축은 LLM
판정 없이도(코드로) 잴 수 있는 것들이라 여기 먼저 추가한다 - "답이 맞는지"
(correctness/faithfulness, LLM 판정 필요)와는 별개로 "근거를 제대로
인용했는지" / "기권 판단이 맞는지"는 결정론적으로 확인 가능하다. 이 모듈이
이제 재는 것: (1) check_required_facts - 기존 어휘 매칭, 여전히
diagnostic-only로 취급할 것(§8.7 계약과 동일한 이유 - 동의어/자연스러운
표현 차이를 놓친다), (2) extract_cited_doc_ids/compute_citation_coverage -
답변이 실제로 인용한 문서 vs 필요한 문서, (3) is_abstention/
compute_abstention_match - 기권 여부가 골든셋 기대(decision/answerability)와
일치하는지. correctness/faithfulness/completeness처럼 의미 판단이 필요한
축은 여전히 LLM 판정이 있어야 재는 게 맞고, 아직 우리 쪽엔 없다(팀원
judge-config.json 재사용 여부는 별도 논의 중).
"""
from __future__ import annotations

import re

DEFAULT_GENERATION_MODEL = "gpt-5-mini"

# [2026-09-02 저녁] 기존 프롬프트에 "답변 마지막 줄에 실제로 근거로 쓴 출처를
# 명시하라"는 지시를 추가했다 - 이래야 답변에서 어떤 doc_id를 인용했는지를
# 코드로 파싱해서(EXTRACT_CITED_DOC_IDS 참고) required_doc_citation_coverage를
# 잴 수 있다. build_context()가 각 근거 블록 앞에 "[출처: {doc_id}]"를 이미
# 붙여주고 있으므로 모델이 그 doc_id를 그대로 복사해 쓰면 된다. 기존 답변
# 내용(사실/숫자)에는 영향이 없고 마지막에 한 줄만 추가되는 형식이라
# check_required_facts 채점에는 영향을 주지 않는다(기존 단어들은 그대로 남음).
ABSTENTION_PHRASE = "제공된 문서에서 확인할 수 없습니다"

# [2026-09-03 추가] 프롬프트 엔지니어링 - step14 재채점(is_abstention 버그
# 수정) 이후 남은 불일치 3건(g22/g24/c25, daily-briefing 저녁 6 참고)을
# 다시 원문으로 뜯어보면 두 가지 서로 다른 패턴이었다:
#   (1) c25(decision="source_conflict" - 근거 문서들이 서로 다른 내용을
#       담고 있어 "상충한다"고 알려주는 게 정답인 문항)에서 모델이 그냥
#       "확인할 수 없습니다"로 완전 기권해버렸다 - 상충 자체를 감지하고
#       설명하라는 지시가 프롬프트에 전혀 없었으니 당연한 결과. 이건
#       프롬프트로 명확히 고칠 수 있는 부분이라 아래에 지시를 추가했다.
#   (2) g22/g24(decision="abstain" - 질문 전체가 기권 대상인 문항)에서는
#       모델이 오히려 질문의 "일부"(예: 예산 총액)는 근거에 있어서 답하고,
#       나머지 하위 질문(시장 평균과의 비교)만 기권했다 - 즉 "아는 건 답하고
#       모르는 건 기권"이라는, 원래 바라던 바로 그 행동을 한 것인데, golden
#       set은 이 문항 전체를 "완전 기권이 정답"으로 채점하고 있다. 이건
#       프롬프트를 어느 쪽으로 튜닝해도 다른 쪽이 희생되는 근본적인 긴장
#       관계라(부분 정보라도 알려주는 게 사용자에게 더 유용할 수 있음),
#       "무조건 다 기권하라"고 강제하는 지시는 넣지 않았다 - 실사용
#       관점에서 오히려 퇴보일 수 있다고 판단(daily-briefing에 한계로 기록,
#       프롬프트로 강제 교정하지 않기로 함).
# 그래서 이번엔 (1) 상충 정보 처리 지시를 새로 추가하고, 기존에 모델이
# 이미 잘 하고 있던 (2)류 행동(부분 답변 - is_abstention 버그 수정 전에는
# 이걸 "오분류"로 잘못 벌점 주고 있었을 뿐, 모델 행동 자체는 문제 없었음)을
# 명시적으로 지시에 넣어 더 일관되게 만들었다.
SYSTEM_PROMPT = (
    "당신은 공공/기업 RFP(제안요청서) 문서에 대해 답변하는 어시스턴트입니다. "
    "아래 [검색된 근거]에 실제로 있는 내용만 근거로 답변하세요. "
    f"근거에 없는 내용은 추측하지 말고 '{ABSTENTION_PHRASE}'라고 답하세요. "
    "답변은 간결하게, 핵심 사실(숫자/날짜/기관명 등)을 정확히 포함해서 작성하세요. "
    "질문에 여러 하위 항목이 포함된 경우, 항목별로 근거에서 확인되는 내용은 "
    "각각 답하고, 확인되지 않는 항목에 대해서만 그 항목에 한정해서 위 문구를 "
    "사용하세요 - 질문 중 일부라도 근거에서 확인 가능하다면 질문 전체를 "
    "기권하지 마세요. "
    "서로 다른 근거 문서(또는 같은 문서의 서로 다른 부분)가 같은 항목에 대해 "
    "다른 내용을 담고 있다면(예: 원공고와 정정공고의 금액이 다름), 기권하지 "
    "말고 각 근거에 어떤 내용이 있는지 구체적으로 설명하고 그 사이에 차이 "
    "(상충)가 있다는 점을 답변에 명시하세요. "
    "기권하는 경우가 아니라면, 답변의 마지막 줄에 실제로 근거로 사용한 출처를 "
    "'[근거: doc_id1, doc_id2]' 형식으로(근거 블록 앞의 [출처: ...]에 있는 "
    "doc_id를 그대로 사용) 표시하세요. 사용하지 않은 출처는 포함하지 마세요."
)


def build_context(hits) -> str:
    parts = []
    for h in hits:
        parts.append(f"[출처: {h.doc_id}]\n{h.text}")
    return "\n\n---\n\n".join(parts)


def generate_answer(client, query: str, context: str, model: str = DEFAULT_GENERATION_MODEL) -> str | None:
    user_prompt = f"[검색된 근거]\n{context}\n\n[질문]\n{query}"
    try:
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.output_text
    except Exception as e:  # noqa: BLE001
        print(f"  ! 생성 실패: {e}")
        return None


def _norm_for_fact_match(s: str) -> str:
    """공백/쉼표 제거. [2026-09-01 수정] golden-set-v3-share의 required_fact_groups가
    금액을 쉼표 없는 순수 숫자로 적어둔 경우가 많다(예: ["999494600"]) - 그런데
    gpt-5-mini는 자연스러운 한국어 표현대로 "999,494,600원"처럼 천단위 쉼표를
    넣어서 답하므로, 공백만 지우고 비교하면 쉼표 하나 때문에 사실은 맞는 답을
    틀렸다고("부분 문자열 아님") 오판하게 된다. 답변/정답 양쪽 다 쉼표까지
    지우고 비교해서 이 오탐을 없앤다."""
    return str(s).replace(" ", "").replace(",", "")


# [2026-09-02 추가] "2024년 10월 31일" / "2024-10-31" / "2024. 10. 31." /
# "20241031"은 전부 같은 날짜인데 표기만 다르다 - RFP 원문 자체가 "2024. 10.
# 31."처럼 마침표+공백으로 날짜를 적는 경우가 흔해서(golden-set-v3-share
# supplemental-qa-c02에서 실제 확인됨), gpt-5-mini가 원문 표기를 그대로
# 따라 답하면 required_fact_groups에 없는 포맷이라는 이유만으로 오탐 Fail이
# 난다. 연/월/일 숫자만 뽑아 8자리(YYYYMMDD)로 정규화해서 비교하면 표기
# 방식과 무관하게 같은 날짜인지 판단할 수 있다. 구분자(.,-,년/월/일)가
# 있어도 없어도(20241031) 매칭되도록 전부 선택 사항으로 뒀다.
_DATE_RE = re.compile(r"(\d{4})\s*[.\-/년]?\s*(\d{1,2})\s*[.\-/월]?\s*(\d{1,2})\s*일?")


def _extract_dates_as_digits(s: str) -> set[str]:
    """문자열에서 날짜로 보이는 부분을 전부 찾아 YYYYMMDD 숫자 문자열 집합으로
    정규화해서 반환한다(표기 방식이 달라도 같은 날짜면 같은 문자열이 됨)."""
    out = set()
    for m in _DATE_RE.finditer(str(s)):
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        out.add(f"{y}{mo}{d}")
    return out


def check_required_facts(answer: str, required_facts) -> tuple[int, int]:
    """required_facts: [["한영대학교"], ["1억", "100,000,000원"], ...] 형태
    (사실 하나당 인정 가능한 표현들의 리스트). 답변 문자열에 각 사실 그룹 중
    하나라도 들어있으면 그 사실을 "맞춘 것"으로 센다.
    반환값: (맞춘 사실 수, 전체 사실 수).

    [2026-09-02 수정] "VAT 포함", "부가가치세 별도" 처럼 두 단어로 된 variant를
    지금까지는 통째로 하나의 연속 문자열로 찾았는데, golden-set-v3-share
    supplemental-qa-c06/c08 재실행 결과를 보니 이게 오탐(사실은 맞는데 Fail
    처리)을 낸다: gpt-5-mini는 "부가가치세(VAT) 포함" 처럼 괄호로 뜻을
    풀어 쓰거나 "부가가치세는 별도" 처럼 조사(는/은/이/가)를 자연스럽게
    끼워 넣는데, 그러면 "부가가치세 포함"/"부가가치세 별도"가 연속 문자열로
    안 걸린다. 심지어 golden set 자신의 reference_answer("VAT가 포함된")도
    이 기준으로는 스스로 통과 못 하는 걸 확인했다 - 즉 연속 문자열 요구 자체가
    채점 기준의 결함이었다. 그래서 variant를 공백 기준으로 단어 단위로 쪼갠
    뒤, 그 단어들이 (순서/인접 여부와 무관하게) 답변 어딘가에 각각 들어있으면
    인정하도록 완화했다. 기존에 연속 문자열로 통과하던 케이스는 이 조건도
    당연히 만족하므로 패스->fail로 역행하는 경우는 없다.

    [2026-09-02 추가 수정] 위 완화를 적용한 뒤 재실행한 supplemental-qa-c02가
    여전히 Fail이었다 - required_fact_groups는 날짜를 ["2024년 10월 31일",
    "2024-10-31", "20241031"] 중 하나로 기대하는데, 생성된 답변은 원문 표기를
    그대로 따라 "2024. 10. 31."이라고 답했다. 단어 단위 매칭으로는 "2024년"
    같은 단어가 "2024."와 다른 문자열이라 여전히 못 잡는다. 그래서 각
    variant/answer에서 날짜로 보이는 부분을 _extract_dates_as_digits()로
    YYYYMMDD 숫자로 정규화해 비교하는 걸 fallback으로 추가했다 - 단어
    매칭이 실패해도 날짜 숫자가 일치하면 그 사실을 맞춘 것으로 인정한다."""
    if not isinstance(required_facts, list) or len(required_facts) == 0:
        return 0, 0
    answer_norm = _norm_for_fact_match(answer)
    answer_dates = _extract_dates_as_digits(answer)
    matched = 0
    for fact_group in required_facts:
        variants = fact_group if isinstance(fact_group, list) else [fact_group]
        group_matched = False
        for v in variants:
            words = str(v).split()  # 공백 기준으로 단어 분리 (예: "VAT 포함" -> ["VAT", "포함"])
            if words and all(_norm_for_fact_match(w) in answer_norm for w in words):
                group_matched = True
                break
            variant_dates = _extract_dates_as_digits(v)
            if variant_dates and (variant_dates & answer_dates):
                group_matched = True
                break
        if group_matched:
            matched += 1
    return matched, len(required_facts)


# [2026-09-02 저녁 추가] 아래부터 required_doc_citation_coverage /
# abstention_behavior_match 계산 - 모듈 docstring의 "2026-09-02 저녁 추가"
# 절 참고. 둘 다 LLM 호출 없이 결정론적으로 계산된다.

# [2026-09-02 밤 - 버그 수정] 기존 정규식 r"\[\s*근거\s*:\s*([^\]]+)\]"은
# "]"가 나오는 첫 지점에서 멈춘다. 그런데 이 코퍼스는 RFP 파일명 자체에
# "[재공고][긴급][협상형]..." 처럼 대괄호 태그가 흔히 박혀 있어서, 인용된
# doc_id가 이런 파일명이면 그 안의 첫 "]"에서 잘려버린다(예:
# "한국철도공사 (용역)_[재공고][긴급][협상형]운행정보기록 자동분석시스.hwp"가
# "한국철도공사 (용역)_[재공고"로 잘림) - required_doc_citation_coverage를
# 실제로는 맞게 인용했는데도 실패로 채점하는 원인이었다(v3_answer56_
# generation_compare.csv 재검토로 5건 확인: c09/c11/c16/g06/g15).
# 프롬프트가 "[근거: ...]"를 답변의 "마지막 줄"에 쓰라고 지시하므로, 그
# 안에 "]"가 몇 개 끼어 있든 "문자열 끝까지"를 통째로 캡처한 뒤 맨 마지막
# "]" 하나만 닫는 괄호로 보는 게 맞다 - 탐욕적(.+) 매칭이 문자열 끝의
# "]\s*$"를 만날 때까지 최대한 먹고 들어가므로 안쪽 대괄호들은 내용의
# 일부로 자연히 포함된다. re.DOTALL은 모델이 줄바꿈을 두 번 넣는 등
# "마지막 줄"이 살짝 어긋나도 잡아내기 위한 여유.
_CITATION_LINE_RE = re.compile(r"\[\s*근거\s*:\s*(.+)\]\s*$", re.DOTALL)


def extract_cited_doc_ids(answer: str) -> list[str]:
    """답변 마지막 줄의 '[근거: doc_id1, doc_id2]' 형식에서 인용된 doc_id
    목록을 뽑는다. 못 찾으면 빈 리스트(= 아무것도 인용 안 한 것으로 취급 -
    모델이 형식을 안 지켰거나 기권한 경우 등)."""
    if not answer:
        return []
    m = _CITATION_LINE_RE.search(answer)
    if not m:
        return []
    raw = m.group(1)
    return [d.strip() for d in raw.split(",") if d.strip()]


def compute_citation_coverage(answer: str, required_doc_ids) -> tuple[int, int]:
    """답변이 실제로 인용한 문서 중 필요한 문서가 몇 개 포함됐는지.
    반환값: (인용된 필요 문서 수, 전체 필요 문서 수). 팀원 쪽
    required_doc_citation_coverage와 같은 개념 - "검색이 찾았는지"(recall)가
    아니라 "답변이 실제로 그 문서를 인용했다고 밝혔는지"를 잰다."""
    required = list(required_doc_ids) if isinstance(required_doc_ids, (list, set, tuple)) else []
    if not required:
        return 0, 0
    cited = set(extract_cited_doc_ids(answer))
    matched = sum(1 for d in required if d in cited)
    return matched, len(required)


# [2026-09-02 밤 - 버그 수정] 기존 구현은 "ABSTENTION_PHRASE가 답변 어디에든
# 있으면 기권"이었다. v3_answer56_generation_compare.csv를 직접 열어
# 11건의 abstention_match 불일치를 전수 조사한 결과 두 방향의 오탐이 확인됐다:
#   (1) 다중 답변(여러 하위 질문에 답하는 문항)에서 그중 "일부만" 모른다고
#       답한 경우(예: c12 - "하도급 가능 여부: 제공된 문서에서 확인할 수
#       없습니다. \n공동수급 관련 조건: [실질적인 실제 답변]") - 실제로는
#       상당 부분을 답했는데도 문구가 한 곳에 있다는 이유만으로 "완전 기권"으로
#       오분류됐다. 9건(c12/c13/c19/c25/g12/g13/g14/g19/g23)이 이 유형.
#   (2) 반대로 실제 완전 기권인데(rag-56의 decision=="abstain" 2건, g22/g24)
#       모델이 프롬프트가 지시한 정확한 문구("제공된 문서에서 확인할 수
#       없습니다") 대신 표현을 바꿔("...확인할 수 없습니다"류, "제공된
#       문서에서" 접두어 없이) 답해서 아예 못 잡힌 경우.
# 두 문제 다 "문구가 텍스트 안에 있는지"만으로는 풀 수 없고, "그 문구를 뺀
# 나머지에 실질적인 내용이 남는지"를 봐야 한다. 그래서: (a) 탐지 문구를
# ABSTENTION_PHRASE(정확한 지시 문구)보다 짧은 핵심부("확인할 수 없습니다")로
# 넓혀서 (2)의 표현-변형도 잡고, (b) 줄 단위로 쪼개서 각 줄에서 그 핵심
# 문구를 제거하고 남는 텍스트가 "짧은 라벨/조사 수준"인지 "실질적인 사실
# 내용"인지를 길이로 구분해 (1)의 다중 답변 오탐을 없앤다 - 문구가 없는 줄에
# 유의미한 길이의 내용이 하나라도 남으면 "일부는 답했다"는 뜻이므로 완전
# 기권이 아니다. 완벽한 의미 판단은 아니지만(예: 질문 자체를 길게 되풀이하는
# 라벨이 있으면 오판 가능), 실제 11건 오탐 사례에는 모두 들어맞는 걸
# 확인했다.
_ABSTENTION_CORE_PHRASE = "확인할 수 없습니다"
_ABSTENTION_LINE_SUBSTANTIAL_LEN = 15  # 이 길이 이상 "실질 내용"이 남으면 그 줄은 답변으로 간주


def is_abstention(answer: str | None) -> bool:
    """답변이 (부분이 아니라) 완전히 기권인지 판단한다. 생성 자체가 실패한
    경우(answer is None)도 기권으로 취급한다."""
    if answer is None:
        return True
    body = _CITATION_LINE_RE.sub("", answer).strip()
    if _ABSTENTION_CORE_PHRASE not in body:
        return False
    for line in body.splitlines():
        remainder = line.replace(ABSTENTION_PHRASE, "").replace(_ABSTENTION_CORE_PHRASE, "")
        remainder = re.sub(r"[\s.,:;\-·※]+", "", remainder)
        if len(remainder) >= _ABSTENTION_LINE_SUBSTANTIAL_LEN:
            return False  # 기권 문구를 뺀 나머지에 실질 내용이 남아있음 -> 부분 답변, 완전 기권 아님
    return True


def compute_abstention_match(answer: str | None, expected_should_abstain: bool) -> bool:
    """실제 기권 여부가 골든셋이 기대하는 기권 여부와 일치하는지.
    `expected_should_abstain`은 호출하는 쪽에서 golden set의 상태 필드로
    직접 계산해서 넘긴다 - v6 golden set은 answerability(!= 'answerable'이면
    기권 기대), golden-set-v3-share는 decision(in ['abstain',
    'source_conflict']이면 기권 기대)처럼 데이터셋마다 필드명이 달라서
    이 함수 안에서 하드코딩하지 않았다. 팀원 쪽 abstention_behavior_match와
    같은 개념."""
    return is_abstention(answer) == expected_should_abstain
