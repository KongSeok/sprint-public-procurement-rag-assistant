# Evidence-Harness 전환 플랜
작성: 2026-09-02 · branch: feat/evidence-harness-v1 · base: 7ad229f
상태: IN_PROGRESS · 실행: hybrid (독립 모듈 병렬, 통합/릴레이 순차)

## 목표와 범위
한 번 검색 후 생성하는 경로를 근거 객체 + 외부 상태 + 제한된 반복 검색 경로로 전환한다.
사용자의 "실험 완료"는 계획 전제이며 실제 모델·정책 checkpoint 존재/승인을 뜻하지 않는다.
두 연구 문서의 결합: opt-arch의 evidence/retrieval substrate 위에 evoHarness의 controller.
기존 Git HEAD에서 독립 worktree를 만들었다. 원본 작업 폴더의 미커밋 parser/UI/골드 변경은 보존한다.

## 고정점과 변경점
- corpus/parser/provenance/gold/semantic judge는 하네스의 읽기 전용 영역.
- page-only는 기존 CLI로 재현; 새 명령은 opt-in. 실행 프로필 전환으로 rollback.
- EvidenceStore → RetrievalTools → Harness → GeneratorAdapter. 학습/평가는 런타임 밖.
- query/history로 계획한 slots만 사용. gold의 required-doc/required-facts는 런타임에 전달 금지.
- 기존 Mac 실측 generator는 qwen3.8:27b-mlx; Qwen3-8B-AWQ는 GCP 목표.
- 이전 HTML의 65~70/78~82 예측은 검증된 성능 근거로 채택하지 않는다.

## 배치와 완료 기준
| ID | 목표·범위 | 선행 | 검증/완료 기준 | 상태 |
| --- | --- | --- | --- | --- |
| EH0 | 플랜·계약·TODO·target/current flow·branch 고정 | 없음 | 문서 경로 및 첫 GAP 점수표 | IN_PROGRESS |
| EH1 | evidence 객체, page parent, text children, table/figure bridge | EH0 | identity/hash, orphan/cross-doc 거부, source adapter tests | TODO |
| EH2 | dense/lexical/visual ports, RRF, rerank, doc-diverse context | EH1 계약 | scope 적용·중복 제거·rank trace·budget 검증 | TODO |
| EH3 | query plan, Belief/Progress, typed actions, missing-slot loop | EH1/EH2 | 재검색→bridge→verify→stop, error/budget/contradiction tests | TODO |
| EH4 | provider adapter·CLI·private trajectory·shadow rollback·diagnostic | EH3 | 합성 end-to-end 경로 + 기존 baseline 회귀 + lineage | PREPARED (live smoke pending) |
| EH5 | 모델/정책/하드웨어 preflight 및 운영 승격 | EH4 | 고정 모델·승인 qrel·자원·heldout 실측 있어야 승격 | BLOCKED (pins absent) |
| EH6 | SFT/RL 및 offline evolution 연결 | EH4/EH5 | 승인 train/holdout·policy checkpoint; gold 누출 없는 trajectory export | PREPARATION_ONLY |

EH1~4는 다운로드 없는 로컬 구현과 합성 검증부터 수행한다.
EH5/6은 누락된 모델·policy·승인 근거를 확인하여 구현 가능한 준비 작업을 끝내고 실제 차단 사유를 기록한다.
새 API corpus egress나 유료 GPU, 외부 모델 다운로드는 현재 로컬 구현 범위에서 자동 실행하지 않는다.
공식 전환이 불가능해도 준비된 경로와 차단 지점을 구별한다.

## 실제 접점
기존 answering/pipeline.py, answering/generation.py, stacks/{api,local},
indexing/{exact_index,embeddings,fusion}, ingest의 page/table/visual 산출물을 재사용/adapter로 연결.
기존 strict schema를 느슨하게 고치지 않는다. 새 trace는 독립 sidecar.

## 검증 전략
1. unittest: evidence 무결성, scope, budget, policy action 유효성, retained evidence coverage.
2. 통합: 합성 A/B 비교에서 누락 속성 하나를 table bridge로 채우는 실제 runtime 경로.
3. 오류: 잘못된 citation, unknown evidence, false stop, context overflow, 도구 실패는 명시적 종료.
4. CLI: private 출력과 content-free stdout, dry preflight, baseline rollback, trajectory export.
5. 기존 관련/full 회귀와 repository safety; Mermaid PNG/HTML 브라우저 확인.
6. semantic correctness 평가는 고정 LLM만 수행. 코드는 구조/집합 수치만 계산.

## 운영 전환
모델과 정책이 검증되면 opt-in shadow → 승인된 프로필 rollout. 자동 이중 외부 호출은 하지 않는다.
훈련·harness code evolution은 offline만 허용. 평가 도중 gold, parser, IDs, judge 수정 금지.
품질/자원 gate 실패 시 baseline profile로 복귀하며 실패 trace는 보존한다.

## 산출물
- 계약: ../architecture/specs/evidence-harness-contract.md
- TODO: ../architecture/todolist.md (Evidence-Harness 절)
- 릴레이: evidence-harness-relay.md
- 플로우: ../architecture/specs/evidence-harness-flow-validation.md 및 HTML/PNG
