# B3 이후 context 연결 — 설계 검토 초안

상태: READ_ONLY_PREVIEW. B3 최종 검증·검수·마감 전이며 다음 배치 선정·구현 승인이 아니다. 현재 후보와 실행 중인 검사는 수정하지 않았다.

## 목표와 바로 다음 공백

기준선 대비 검색 품질과 효율을 비교할 수 있도록 challenger의 끊어진 경로를 연결한다. 현재 B3는 첫 obligation의 ordinal4 parent 하나를 실행하면서 complete parent/bridge batch를 준비한다. 후속 decision은 revision4를 아직 받지 않는다.

다음 검토 후보는 후속 decision만 추가하는 작은 배치가 아니라, 첫 obligation의 남은 context 선택·소비·effect/transition/readback까지 묶은 한 배치다. 관련 leaf별 집중 검사 후 한 번의 통합 gate로 검증하며 rerank·semantic 실행은 별도 경계로 둔다.

## 먼저 결정해야 할 시간 경계

준비된 sibling receipt는 다음 action의 claim보다 먼저 존재한다. 기존 post-claim source 규칙에 임의로 예외를 주거나 새 시간표시를 붙이면 안 된다. batch를 다시 만들면 once-only 준비 계약과 충돌한다.

Philosopher의 권고 초안은 별도 private prepared-consumption authority다.

- authentic revision4/성공 ordinal4 transition이 보유한 exact complete tuple과 preparation claim을 원천으로 삼는다.
- 같은 root/첫 obligation·canonical role/target·exact receipt identity·미소비 항목을 검증한다.
- 후속 exact decision/새 claim 뒤에 소비 증명을 발급한다. 원본 receipt의 epoch·hash·authority를 변경하지 않는다.
- 원본 준비 시점과 현재 소비 시점을 별도 경계로 검증한다. 실패한 준비·다른 root·이미 소비된 항목·외부 batch는 거절한다.

기존 context effect는 call_performed=true로 정규화된다. 준비된 source 소비에 같은 의미를 재사용하면 새로운 store 작업으로 오해할 수 있으므로, 다음 정식 Design에서는 새 prepared-consumption source 종류와 call_performed=false 조합, 단계별 준비/소비 계수 및 schema 호환성을 명시적으로 검토한다. 이는 현재 계약 변경 승인이 아니다.

## 이후 정식 Design에서 고정할 것

1. complete tuple의 canonical 순서와 소비 이력·예산·한 action당 한 항목/effect.
2. 준비 이후 소비 authority·source normalization·effect matrix의 정확한 계약. 기존 stale-source 검사는 유지한다.
3. parent/bridge applied·empty 결과와 state/fingerprint 규칙. parent 문맥을 정답으로 승격하지 않는다.
4. 동시 실행·중복·실패 소비·zero redispatch readback·sibling/원본 state 보존·context 종료 후 다음 자격.
5. rerank/semantic/absence/후속 obligation/terminal까지 완료했다고 표기하지 않는다.

대안은 empty-fusion의 exhaustion→absence 실행이다. 비교적 독립적인 다음 후보지만 applied context 경로를 잇지는 않는다. B3 마감 뒤 TODO 우선순위와 함께 최종 선정한다.

## 근거 위치

- `src/midprojectrag/orchestration/execution_contracts.py`: revision4 decision 공백, context source 정규화와 temporal admission, accumulator, 첫 parent executor.
- `fivecircles/architecture/specs/controller-first-parent-transition.md`: complete batch provenance, selected-only effect, temporal source fence.
- `fivecircles/architecture/specs/controller-next-decision.md`: ordinal4 선택과 후속 범위.
- `fivecircles/architecture/specs/bidfit-evidence-harness-v1-rc0.md`: action/source/outcome/call matrix, complete tuple·per-target 선택, rerank·derived semantic 경계.

읽기 전용 검토: /root/b3_resume_design. 코드·계약·기본 실행 경로·Git 변경 없음. 실제 다음 Design/GO는 B3 마감 이후 별도 기록한다.
