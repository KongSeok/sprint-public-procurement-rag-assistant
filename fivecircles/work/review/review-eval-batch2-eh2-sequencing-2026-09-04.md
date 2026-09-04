# Review: 평가 Batch 2와 Evidence-Harness Phase 2 실행 순서

날짜: 2026-09-04
검토 상태: `REQUEST_CHANGES` → 사용자 지시에 따라 EH Phase 2 하위로 통합

## Scope

- 기존 `Batch 2 — 평가 세트와 공통 계약 선확정`을 EH Phase 2보다 전부 먼저 끝낼지 검토한다.
- 평가 인프라와 EH 무결성 계약의 중복 소유권을 정리한다.
- retriever 전후 평가에 필요한 기록 계약을 EH2.6 구현 전에 고정할 범위를 정한다.
- visual/VLM TODO는 사용자의 최신 지시에 따라 변경하지 않는다.

## Findings

1. **Batch 2 전체를 직렬 선행시키는 것은 부정확하다.** 공개 평가 Schema, 누수 검사, hash,
   `validate/score/compare` CLI는 이미 `READY_PRIVATE_GOLD`다. 이를 EH Phase 2에서 다시 구현하면
   중복이다.
2. **평가 계약의 작은 delta는 EH2.6.b3/b4보다 먼저 필요하다.** 같은 질문의 dense/lexical raw 후보,
   fusion 후 후보, rerank 후 후보와 최종 context를 구분하지 않으면 pre-context→post-context
   evidence retention을 사후에 재구성해야 한다.
3. **`dev 40문항 작성` TODO는 현재 상태와 다르다.** 실제 40건 draft와 52개 source-block evidence
   reference는 자동 검증을 통과했다. 남은 일은 named human 승인이다. 실제 held-out 20은 아직 없다.
4. **전후 평가용 질문을 새로 두 벌 만들면 안 된다.** 한 질문과 한 qrels를 유지하고 각 stage의
   candidate/context ID를 별도 receipt로 저장해야 한다.
5. **gold qrels는 실험별 chunk ID가 아니라 안정적인 source anchor가 기준이다.** text는
   `doc_id + source_block_id + locator_hash`, visual은 승인된 occurrence/object locator를 사용한다.
   실험별 Evidence ID는 evaluator-only resolution receipt로 anchor에 매핑한다.
6. **`EVAL-HOLDOUT` 하나로 이름을 바꾸는 것도 범위가 좁다.** 소유권은
   `EVAL-FOUNDATION`(완료된 인프라), `EVAL-GOLDSET`(dev 승인·held-out 제작/봉인),
   `EVAL-RUN`(최종 실행)으로 나누는 편이 명확하다.
7. **RAG129는 이미 실행·검토된 개발/회귀 자산이다.** 진짜 sealed held-out 20의 포함 방식은
   기존 129 count 계약과 충돌하므로 작성 전에 별도 결정이 필요하다. 이미 노출된 문항을 이름만
   held-out으로 바꾸면 안 된다.

## Decision

`REQUEST_CHANGES`.

- 평가 Batch 2의 남은 책임을 EH Phase 2의 `EH2.EVAL` 하위로 흡수한다.
- 완료된 평가 인프라는 재구현하지 않고 참조한다.
- `EH2.EVAL`의 stage checkpoint/qrels projection 계약만 `EH2.6.b3`의 직렬 선행 gate로 둔다.
- dev 사람 승인과 held-out 작성·교차검토는 EH2 구현과 병행한다.
- EH2.G는 합성 E2E, gold-injection 차단, lineage와 controller 종료 회귀를 유지한다.
- 실제 held-out 실행과 우승/승격 판정은 최종 config 동결 뒤 `EH4.10~11`에서 한 번만 수행한다.

## Next actions

1. `evaluation-contract.md`에 공통 stage checkpoint와 evaluator-only join 규칙을 추가한다.
2. EH2 계약/TODO에 `EH2.EVAL`을 넣고 `EH2.6.b3` 선행 관계를 명시한다.
3. 기존 dev40 TODO를 신규 작성이 아니라 named human 승인으로 정정한다.
4. held-out 20의 count 계약과 격리 책임자를 확정한 뒤 작성·2인 검토·hash 봉인한다.
5. 위 계약 delta가 고정되면 `EH2.6.b3` 구현을 계속한다.
