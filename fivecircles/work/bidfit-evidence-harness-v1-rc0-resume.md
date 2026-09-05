# EH-RC0: 여기부터 재개

작성 시점: 2026-09-03. 이 파일은 짧은 복구 안내이며 최신 상태는 checkpoint가 우선한다.

실행 안내 갱신(2026-09-05): 검색 비교 선행으로 TODO를 재구성했다. 현재 권위는 TODO 상단 실행 큐와
`2026-09-05-search-first-relay.md`의 최신 cycle이다. 아래 '저장 당시'와 ZIP은 역사 스냅샷이다.

## 다른 작업/세션에 붙여 넣을 재개 프롬프트

```text
BidFit Evidence-Harness v1-rc0 작업을 재개한다.
작업 repo는 /Users/pio/Documents/AIENGINEERCOURSE/MidProjectRAG 이다.
ambient cwd의 /Users/pio/Documents/ChatGPT/MidProjectRAG 는 다른 사본이므로 사용하지 않는다.

먼저 fivecircles/work/bidfit-evidence-harness-v1-rc0-checkpoint.md 를 읽고
실제 branch/HEAD/dirty 상태와 대조한다. 저장 시 branch는 `feature/visual-retrieval`이었고
2026-09-04에 `feat/total-integration`으로 이름을 변경했다.
HEAD는 7ad229f8c85fb48ebb1c53f4424db4a224b562a7 이었다.
다르다고 checkout/reset하지 말고 변경 경위를 확인한다.

fivecircles/architecture/todolist.md 상단 실행 큐에서 현재 leaf 하나만 선택한다.
한 번에 하나를 계약 확인→테스트→구현→focused 검증→체크포인트 순으로 처리한다.
크면 .a/.b처럼 다시 나눈다. 완료한 감사와 전체 문서를 매번 다시 읽지 않는다.
EVAL.4.a/b와 draft/recorder·로컬12회 smoke는 완료했다. 현재 다음은 EH4.7c.1.a/b/c 순위 지표·doc qrels·CLI다.
그다음 실제 recorder smoke → retrieval 지표/승인 조건 동결 → 3종 검색 비교다.
EH2.6.c4.0.e는 기술 READY/우선순위 대기로 보존했다. Controller 전체 완료를 첫 비교 선행조건으로 오해하지 않는다.
기존131 질문/답변과 보조69 검수는 유지하며, 부족한 위치 qrels와 정형 승인 필드는 별도 표시한다.

애매하면 ZIP의 사용자 원문 prompts/original-implementation-request.txt 및
prompts/latest-user-directions.md, 해당 계약 절을 확인한다.
원문 요구사항은 요약보다 우선하며 저장 이후의 명시적 사용자 지시가 최우선이다.
core implementation, 실물 모델 실행, 성능 검증은 구분해 보고한다.
사용자 dirty 변경과 resources 원본은 보존하고 branch 변경/통째 merge/force push/overwrite는 하지 않는다.
```

## 읽는 순서 / 판단 근거

1. 최신 checkpoint: 현재 leaf, 통과 명령, 다음 단계. ZIP 안의 사본은 저장 당시 스냅샷일 뿐이다.
2. TODO의 현재 leaf와 `architecture/specs/bidfit-evidence-harness-v1-rc0.md` 해당 절.
3. 애매할 때만 원문 프롬프트 해당 절, `assembly-on-research-and-exp.md`, research 문서.
4. 실제 코드/현재 Git 상태로 문서의 구현 주장을 검증한다. 다른 브랜치 코드는 읽기 전용 참고다.

사용자 첨부에는 최종 완료 기준 **15개**, 내부 계약 §10에는 요약 acceptance **13개**,
최종 응답 형식에는 **13항목**이 있다. 서로 같은 목록으로 간주하지 말고 원문 기준 누락을 검사한다.

## 저장 당시 확정 사실

- 현재 branch: `feat/total-integration` (이름 변경 전 `feature/visual-retrieval`), 시작 HEAD `7ad229f`.
- 시작 시 tracked dirty 39개와 다수 untracked 사용자 파일. 삭제/덮어쓰기 없이 보존.
- 변경 전 테스트: `PYTHONPATH=src .venv/bin/python -m unittest discover -q -s tests -t .`
  → 805 tests, 33.493s, OK, skip 0. 보관 작업에서 다시 실행한 결과가 아니다.
- 완료: 코드 감사, target/current flow 초안, 구현 계약, 재귀 TODO/체크포인트.
- 미완료: 이번 EH-RC0 production 구현, 새 child 임베딩, 새 profile 품질 비교, 최종 push.
- `feat/evidence-harness-v1`은 참고 prototype. 통째 merge하지 않으며 gold-scope fallback,
  page-dense/child-lexical 혼합 같은 문제를 그대로 재사용하지 않는다.
- 기존 KURE page index는 child index가 아니다. 단순 hash embedder 결과를 KURE로 표기하지 않는다.
- metadata 보완과 원문/청크/인덱스 갱신을 같은 작업으로 취급하지 않는다.
- optional Kiwi/Qwen/API 실제 가용성은 해당 실행 leaf에서 재확인한다.

## 작은 context packet

- 목표: immutable Evidence → KURE child + Kiwi BM25 → RRF → E1 bounded harness → verified claims/citations.
- 안전 우선: runtime과 evaluator 정답 분리, empty scope fail-closed, 원본/artifact 불변.
- 단계: P0 integrity/scorer → P1 evidence/retrieval → P2 QueryPlan/loop → P3 analytics/list/table → P4 profiles/eval.
- 제외: full VLM/KoVRE/SFT/RL, 무단 API 과금, corpus 공개, 평가 없는 성능 향상 선언.
- 기술 입력: refined98(94 HWP/4 PDF), page-v1 9,331 chunks, KURE-v1 1,024-d.
- 다음 검증: `PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_runtime_integrity`.
  저장 당시 해당 새 test/module은 아직 없으므로 바로 PASS할 명령이 아니다.

## ZIP의 범위와 보관 위치

- `resources/context-backups/` 아래 timestamp가 있는 ZIP. 기존 ZIP은 덮어쓰지 않는다.
- 포함: 사용자 원문, 최근 지시, 이 안내, 계약/TODO/checkpoint/원샷 원장, flow,
  참고 research Markdown, README/환경 선언/테스트 정책, Git 상태의 목록·통계, SHA-256 manifest.
- 제외: `.env`/키, 앱 source code, raw corpus/gold/qrels, vector/model, 실제 prompt/trace payload,
  `.git` 내부, patch/diff 본문. research 문서는 참고 문서로만 포함한다.
- 이것은 **전체 대화 export 또는 실행 가능한 저장소/dirty 코드 백업이 아니다**.
  원문 첨부만 byte-identical 보관하며 대화 맥락은 본 안내와 최근 사용자 지시로 요약한다.
- 복구할 때 빈 별도 폴더에 압축을 푼 뒤 읽는다. live repo 위에 일괄 덮어쓰지 않는다.
- archive에는 로컬 경로와 내부 연구 자료가 포함되므로 private 유지. 원격 업로드/commit하지 않는다.
