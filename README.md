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

HWP fallback까지 처리하는 격리 Python 환경은 다음처럼 준비합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[hwp]'
source .venv/bin/activate
```

HWP/HWPX 주 추출기는 공식 Release의 체크섬을 검증한 `rhwp v0.8.4` CLI입니다.
OS에 맞는 바이너리는 [공식 v0.8.4 Release](https://github.com/edwardkim/rhwp/releases/tag/v0.8.4)에서
받고 함께 제공되는 `SHA256SUMS.txt`와 대조합니다. 바이너리를 저장소에 커밋하지 말고 절대경로를
명시합니다. Release archive 검증 후 실제 실행 바이너리 자체의 SHA-256도 운영 환경에 고정합니다.

```bash
export MIDPROJECTRAG_RHWP_BIN=/absolute/path/to/rhwp
export MIDPROJECTRAG_RHWP_SHA256=REPLACE_WITH_64_HEX_CHARACTERS
"$MIDPROJECTRAG_RHWP_BIN" --version  # rhwp v0.8.4
```

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
  --require-primary-hwp \
  --rhwp-sha256 "$MIDPROJECTRAG_RHWP_SHA256"
```

HWP/HWPX는 `rhwp export-text --json`의 페이지별 본문과 `export-tables --json`의 병합셀·중첩표
구조를 bounded subprocess에서 읽습니다. 페이지 누락·절단 표시, 표 cell count·span 겹침은
fail-closed로 검사합니다. 페이지는 1-based source locator로 변환하고 표는 caption, 중첩 container
path와 구조화된 셀 metadata를 보존합니다. 표의 페이지·bbox는 별도 render-tree fidelity QA가
끝날 때까지 null입니다.

기준선 임베딩에는 `retrieval_role=primary`인 페이지 본문만 사용합니다. 표 block은
`structured_auxiliary`로 따로 저장해 구조 검색 실험에서만 사용하며, 페이지 본문과 표를 한
인덱스에 무조건 함께 넣지 않습니다. manifest도 primary/auxiliary 문자 수를 분리해 중복 계수를
막습니다. `rhwp`가 실패한 HWP5만 `hwp5txt`, 이어서 같은 원문의 pyhwp binary-model fallback을
사용합니다. fallback 결과는 페이지·표 위치를 보존하지 못하므로 `partial`과 명시적 경고로
남습니다. 의존성이 없거나 원문 해시가 manifest와 달라지면 문서를 누락하지 않고 `failed`
상태와 비식별 오류 코드로 기록합니다.

## 공통 평가 계약

Batch 2는 두 스택이 공유하는 요청·응답 JSON Schema와 단일 문서·다중 문서·후속 질문·기권
평가 계약을 제공합니다. 실제 질문·정답·실행 기록은 Git 밖에 두고, 저장소에는 스키마와 합성
예제만 둡니다.

비교계열의 의미 채점기는 ChatGPT `gpt-5.6-sol`, 루브릭은 `gpt56-semantic-v2`로 고정합니다.
현재 첫 통합 후보 기준선은 `gpt-5-mini`이며 이후 생성 모델과 parser·chunking·embedding·retrieval·
reranking·prompt 스택을 바꿔 비교합니다. 모든 후보는 답변·검색근거·인용·transcript를 먼저
고정하고, Sol은 그 기록을 수정하거나 대체하지 않고 채점합니다. 현재 131개 완료본은 기존 exact
Mini 답변 39개와 prospective 재실행 90개, 로컬 parser 회귀 2개의 계보를 구분한 provisional
기준선이며, 39개 사후 복원 transcript를 숨기지 않습니다.

현재 전체 자산은 RAG 129개와 별도 parser-fallback ETL 회귀 2개, 총 131개입니다. 조건목록의
문서 집합 P/R/F1과 EDA 수치 검사는 Sol 의미점수에 병기하는 객관 지표이며, 파싱 2개는 RAG
평균에 섞지 않고 PASS/FAIL로 따로 보고합니다.

2026-08-31 통합 provisional 기준선은 RAG 평균 54.845/100, accepted 58/129,
rejected 71/129, 미해결 0이며 parser C21/C22는 2/2 PASS입니다. 후보 provider 비용은
USD 0.21345322입니다. 공개 집계는 `evaluation/baselines/mini131-bundle-v1/receipt.json`,
질문·답변·근거·판정 이력이 포함된 131개 검토 화면은 Git 밖 private HTML에 둡니다.

```bash
PYTHONPATH=src python -m midprojectrag.evaluation validate \
  --dev evaluation/templates/dev.example.jsonl \
  --held-out evaluation/templates/heldout.example.jsonl \
  --minimum-per-task 1

PYTHONPATH=src python -m midprojectrag.evaluation score \
  --cases evaluation/private/dev.jsonl \
  --runs artifacts/evaluation/api-dev-runs.jsonl \
  --config evaluation/config/metrics.json
```

실제 평가의 기본 하한은 dev 40문항과 held-out 20문항이며, scoring config와 hard gate가 없거나
약화되면 평가가 실패합니다. 자세한 계약과 리뷰 기준은 `evaluation/README.md`를 따릅니다.

전체 회귀는 프로젝트 `.venv`에서 실행합니다. 아래는 현재 macOS/arm64 개발 환경의 설치·검증 명령입니다.
전체 테스트에 필요한 extras를 함께 설치하고, 기존 ML lock의 버전을 유지합니다.
Linux/GCP 설치는 위 GCP 실행환경 안내를 따릅니다.

```bash
.venv/bin/python -m pip install -e '.[test,rag,evidence-harness,gcp-local,pdf-fidelity,hwp,ui,observability]' -c requirements/gcp-local-lock.txt
.venv/bin/python -m pip check
PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python -m unittest discover -s tests -t . -p 'test*.py'
```

bare `python`은 Miniconda 등 다른 환경을 선택할 수 있습니다. `-t .`은 테스트 간 fixture import의
모듈 이름을 `tests.*`로 통일합니다. 실행환경·실패 처리 규칙은 [테스트 정책](fivecircles/test/testpolicy.md)을 따릅니다.

## 작업 보고 문서

`feat/total-integration` 브랜치의 팀 공유용 작업 보고서는
[박지수 팀원 일지](<박지수 팀원 일지/README.md>) 폴더에 정리되어 있습니다.

| 문서 | 범위 |
| --- | --- |
| [Evidence-Harness 2단계 구현 진행 보고서](<박지수 팀원 일지/2026-09-04-evidence-harness-phase2-progress-report.md>) | EH2.1부터 EH2.6.b2까지의 전체 진행 상황 |
| [EH2.4 비교 근거 누락 방지 보고서](<박지수 팀원 일지/2026-09-04-eh24-compare-doc-field-coverage-report.md>) | 다중 문서 비교의 문서×항목 근거 추적 |
| [EH2.6.b2 실행 경로 보안 강화 보고서](<박지수 팀원 일지/2026-09-04-eh26-b2-runtime-integrity-security-report.md>) | 실행 설정과 검색기 무결성 검증 |
