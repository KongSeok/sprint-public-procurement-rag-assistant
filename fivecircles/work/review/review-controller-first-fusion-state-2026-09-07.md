# 첫 fusion 결과의 후보·잠정 결측 상태 연결 검수

## Scope

- EH2.6.c4.2.b.2 / feat/total-integration. Sol Ultra 구현, 별도 fresh Astra deep 검수.
- 후보 sha256:cc5e19ca5b6a7ab1cc40fe5b62734df3e4a50a760a8274ea7590c1db53058e87; 계약 sha256:1b92dbdf8d116e3812a1e27181e431a9aef39f6e0c70996a70e59dadd3a4c3e8; 증거 sha256:8142e1f1b406947e18d5a650d61229c0576adcad07674018b79949b8fdb45d28.
- [원문 REVIEW](../collaboration/eh-relay-20260907/messages/EH2.6.c4.2.b.2/003-first-fuse-state-review-1.json).

## Findings

- 차단 지적 없음. 실제 fuse 실행→effect→state→전이3로 연결되며 DTO 추가만 한 것이 아니다.
- 첫 obligation만 candidate/provisional_missing으로 바뀐다. effect 근거와 기존 planner/coverage 소유권을 분리 보존한다.
- 형제 항목·선행 실행·원본3계보 보존, 실패 시 부분 state 권한 회수·claim 소비, 재시도·재실행 없음.
- derived state 검증 성공만으로 새 initial root를 만들 수 없다. 기존 source-owner registry가 별도로 필요하다.

## Decision

APPROVE / first-fuse-state-review-1 PASS. 집중25(779.422초)·관련202(230.049초)·격리227(944.217초)·전체1611(1161.717초) PASS, 실패/오류/skip0, exit0.

- 제품/테스트5개(실제 변경4개)+행동 계약2개 고정. 전체·격리 실행의 입력 manifest/환경 전후 동일.
- focused 시작 hash 미기록은 그대로 공개한다. 최종 격리/전체 실행이 동일 후보 증거를 보완한다. 탐색 출력 전사본과 native 최종 로그를 구분했다.
- queue.json 없음: 현재 DIRECTIVE·TODO·debate로 범위 확인. 검수를 위해 동일 전체 테스트를 반복하지 않았다.
- 운영 가드는 현재 필수 검증 면제나 실모델·외부 실행 승인이 아니다. Controller/E2E PARTIAL, 품질 winner 미선정.

## Next actions

1. Keep EH2.6.c4.2.b, EH2.6.d2.x.b, Controller and E2E PARTIAL. This PASS approves only the bound first-obligation fusion candidate and its frozen contracts and required evidence.
2. Select post-fusion eligibility/state handling through a separate complete Design directive. Revision3 fusion leaves semantic state unchanged; both-empty is neither confirmed absence nor answerability.
3. Preserve the shared attempt-start epoch and atomic claim cutoff, exact executor/minter/module/source-kind binding, child and controller once-only consumption, source-derived effects and failure-without-retry behavior.
4. Preserve all predecessor executions, prior decisions and three source lineages. Historical readback must remain non-authorizing and must not redispatch fusion or either retrieval lane.
5. Specify and verify complete canonical sibling-obligation lifetime before executing later compare obligations; do not remint the tuple to recover expired siblings.
6. Keep ordinal4, context, rerank, verify, semantic reducer, follow-up, deadline, terminal and public start/step/run outside this PASS and outside subsequent implementation unless explicitly selected by its authorized directive.
7. Continue synthetic/offline implementation validation without real model/API/provider/Langfuse/VLM/private-data activity or baseline/corpus/gold/evaluation/runtime configuration changes. Keep DIAG131 independently owned and its shared-host diagnostic latency distinct from controlled performance evidence.
8. Any later profiling or optimization selection must follow existing measured-improvement selection authority, potentially EXP-SELECT.3.b. Current test durations do not establish production hotspots or retrieval superiority.
9. Integrate only the reviewed files and bound behavior-affecting documents. Preserve unrelated dirty work and exclude resources from Git. Product, contract or required-evidence changes require a new candidate and review; closeout-only records may remain separate.
10. The preceding nine constraints are retained verbatim from the prior review. Their historical same-state and semantic-reducer exclusions are superseded only by the explicit b.2 prospective amendment: future first fusion now changes the first unsearched obligation to candidate or provisional_missing. All remaining exclusions continue unchanged; historical b.1 artifacts and acceptance must not be rewritten.
11. For subsequent Design, use the exact derived state and authenticated predecessor/source graph. Preserve candidate ordering, untouched sibling identities, effect provenance, open progress, coverage 0.0, in_progress and false terminal gates. Empty fusion must not become confirmed absence or verification readiness.
12. Preserve the reported focused-start fingerprint limitation and development evidence provenance. Final isolated/full evidence provides the authoritative same-candidate binding; do not relabel exploratory transcriptions as native final logs or attribute the full shared-worktree collection wholly to this batch.
13. The accelerator-preflight and impact-based-validation policy additions do not waive this DIRECTIVE's gates or authorize external/model runs. GCP measurements remain separately owned; optional blocked cross-task notices must not be retried without authorization.
