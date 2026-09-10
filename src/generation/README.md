# src/generation/

RFP 질문에 답변을 생성하는 파이프라인. 문서 힌트 추출 → 조건 필터링 →
컨텍스트 구성 → LLM 답변 생성까지 담당한다.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `generation_prompts.py` | 시스템 프롬프트(`SYSTEM_PROMPT_V9`)와 조건부 지시문(`METADATA_DISTINCTION_INSTRUCTION`) |
| `answer_generation.py` | 문서 힌트 매칭, 조건 필터링, 랭킹/집계/다중비교 질문 처리, 최종 답변 생성 함수(`ask_rfp_v9`), 결정론적 후처리 규칙 |

## 핵심 함수

- `ask_rfp_v9()` — 전체 파이프라인의 진입점. 질문 유형(랭킹형/기간형/조건
  필터형/일반 검색)을 감지해 알맞은 경로로 답변을 생성한다.
- `extract_doc_hints_multi()` — 질문에서 정답 문서를 찾는 4단계 매칭 로직
  (기관명 → 사업명/영문 키워드 → 파일명 유사도 → 같은 발주기관 내 문서 선택).
- `apply_keyword_completion()` — 컨텍스트에 있는 정보를 LLM이 반복적으로
  누락하는 경우, 결정론적 규칙으로 답변을 보완하는 후처리. `KEYWORD_
  COMPLETION_RULES`에 문서별로 등록. `__FORCE__` 모드를 쓰면 컨텍스트
  확인 없이 트리거 키워드만으로 무조건 보완 문구를 붙일 수 있다(동의어
  표현 변동 케이스용).
- `apply_answer_replacement()` — 표 파싱 한계로 LLM이 항목-점수 매핑을
  반복적으로 틀리는 경우, 보완이 아니라 답변 본문 자체를 정답으로
  교체하는 후처리.
- `apply_legal_fraction_normalization()` / `apply_score_percent_normalization()`
  — "100분의 N"·"N점" 같은 표기가 LLM 생성마다 "N%"와 오가며 불안정하게
  나오는 것을, 원문을 지우지 않고 옆에 환산값을 병기해 안정화.

각 함수·상수의 개발 배경과 시행착오는 두 파일 상단의 개발 히스토리
주석에 정리되어 있다. 전체 개발 서사는 `docs/generation-pipeline-summary.md`,
검증에 쓰인 실험은 `notebooks/`를 참고.