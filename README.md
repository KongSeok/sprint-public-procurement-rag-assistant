# MidProjectRAG

기업·정부 제안요청서(RFP) 100건을 대상으로 근거 인용형 RAG 시스템을 만들고,
OpenAI API 기반 스택과 GCP L4 기반 로컬 Hugging Face 스택을 동일한 평가 계약으로 비교하는 3주 팀 프로젝트입니다.

## 핵심 사용자 시나리오

1. 단일 RFP에서 요구사항과 주요 정보를 정확히 추출한다.
2. 여러 RFP를 지정된 축으로 비교·종합한다.
3. 이전 대화 맥락을 반영해 후속 질문에 답한다.
4. corpus에 근거가 없으면 추측하지 않고 기권한다.

모든 사실 답변에는 문서와 근거 위치를 인용합니다.

## 구현 전략

- 먼저 단순 청킹 + Dense top-k + 생성 모델의 작동 가능한 기준선을 만든다.
- 검색 실패를 평가한 뒤 구조적 청킹, 메타데이터 라우팅, top-k를 한 요소씩 개선한다.
- MMR, hybrid search, multi-query, reranking은 기준선 이후 실제 실패가 확인될 때만 실험한다.
- 두 실행 스택은 동일 corpus snapshot, 요청/응답 계약, 평가셋을 사용한다.

## 문서 진입점

- 요구사항: `fivecircles/requirements/current.md`
- 확정 결정: `fivecircles/requirements/decisions.md`
- 자료 출처와 데이터 실사: `fivecircles/requirements/sources.md`
- 기술 계약: `fivecircles/architecture/specs/README.md`
- 배치 계획: `fivecircles/architecture/todolist.md`

## 데이터 보안

원본 RFP, 추출 본문, 청크, 벡터 DB, 비공개 평가셋, API 키와 개인정보는 저장소에 커밋하지 않습니다.
과제 가이드의 비밀유지 조항에 따라 공개 가능한 것은 코드, 스키마, 집계 지표,
비식별화된 짧은 예시와 원문을 복원할 수 없는 파생 결과로 제한합니다.

저장소 안전 검사는 다음 명령으로 실행합니다.

```bash
./scripts/validate_repo_safety.sh
```

## 현재 구현된 로컬 수집 CLI

Batch 1은 private 데이터 디렉터리 안에서만 manifest와 추출 산출물을 만들며,
표준 출력에는 집계 상태와 오류 코드만 기록합니다.

```bash
PYTHONPATH=src python -m midprojectrag manifest \
  --data-dir /secure/corpus

PYTHONPATH=src python -m midprojectrag extract \
  --data-dir /secure/corpus \
  --manifest /secure/corpus/private/manifest.jsonl \
  --output-dir /secure/corpus/private/blocks \
  --output-manifest /secure/corpus/private/manifest.extracted.jsonl

PYTHONPATH=src python -m midprojectrag verify \
  --manifest /secure/corpus/private/manifest.extracted.jsonl \
  --blocks-dir /secure/corpus/private/blocks \
  --require-extracted
```

HWP 추출에는 격리 환경의 `hwp5txt`가 필요합니다. 의존성이 없거나 원문 해시가
manifest와 달라지면 문서를 누락하지 않고 `failed` 상태와 비식별 오류 코드로 남깁니다.

개발 환경에서는 프로젝트를 설치하거나 `src` 경로를 명시해 테스트합니다.

```bash
python -m pip install -e .
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v
```
