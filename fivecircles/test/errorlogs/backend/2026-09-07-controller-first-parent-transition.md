# EH2.6.c4.2.b.3 첫 parent 실행 — 개발 검증

## 2026-09-07 22:35 KST — 의도한 RED

- 현상: first-parent-focused-red-1, 1 test/0.000s, failures1/exit1. _execute_controller_first_parent_step 미구현을 정확히 확인했다. 환경/예상 밖 회귀가 아니다.
- 근거: /private/tmp/eh-relay-20260907.GNy8vE/first-parent-focused-red-1-result.json 및 .native.log. 소유2/참조4와 runtime 전후 불변.
- 처리: 동일 Coder가 승인 계약 안에서 구현 중. 아직 해결/PASS 아님; raw RED를 보존한다.

## 검증 준비

- 전체 검증용 capture 사전 검토에서 정확한 파일 역할 집합과 기준 commit의 analytics loader/test/config 결속 검사를 보강했다. 실행 전 helper만 변경했으며 native 테스트 실패가 아니다.
- 기존 resolver finally 복원은 고정 제어흐름+exit 근거로만 기록한다. post-finally 변수값 직접 관측을 주장하지 않는다.

## 2026-09-07 22:50 KST — 승인 전 검증 seal 이동 차단

- Coder 보고: exec_command가 기존 source-attempt registry seal 제거에 같은 patch 안의 대체가 없다는 이유로 실행 전 거절됐다. call/result ID는 도구에 노출되지 않았다고 보고했으며, main이 직접 원시 도구 응답을 재조회한 것은 아니다. 거절된 patch의 적용 bytes는0이다.
- 안전한 수정: 기존 lane/fusion begin·record·claim seal을 보존하고 별도의 한 번만 가능한 parent issuer/minter·accumulator/executor seal을 추가 중이다. 원래 검사를 우회하거나 미검증 대체를 통과로 세지 않는다.
- 상태: 제품 테스트 미완료. executor 정의 후 parent seal 연결·임시 helper 제거·runtime pin 순서를 완성한 뒤, final deep Critic이 두 경로와 실패 시 닫힘을 확인한다. 필요한 계약 확대는 QUESTION으로 처리한다.

## 2026-09-07 22:59 KST — parent 발급 호출 프레임 불일치

- 실제 결과: first-parent-selected-happy-1, 1 test/45.754s, errors1/exit1. 후보 sha256:3aeff009fb9815b2e729aa8914ff08847e17dfa1a001aa47a0e1671504e566c9. 파일/환경 전후 불변, postflight 문제0.
- 원인: parent issuer의 generator expression이 별도 호출 프레임을 만들어 source-attempt begin이 등록된 issuer 코드가 아닌 genexpr에서 호출됐다. controller_source_attempt_begin_authority_required로 정상 경계 검사가 이를 거절했다.
- 조치: 검사를 약화하지 않고 issuer 본문의 직접 반복문에서 시작하도록 Coder가 제한적으로 수정한다. 동일 selected 재검사 후 집중·인접·격리·전체를 순서대로 검증한다. 이 항목은 의도 RED와 다른 구현 실패이며, 아직 해결/PASS가 아니다.
- 근거: /private/tmp/eh-relay-20260907.GNy8vE/first-parent-selected-happy-1-result.json 및 .native.log, native log SHA256=f12833ac2dc5e7a7b19bfc0d8a070fd04631ba8ccb7da493254fe838052d2aa7. main이 결과와 traceback을 직접 확인했다.

## 2026-09-07 23:04 KST — 호출 프레임 수리 재확인

- first-parent-selected-happy-repair-1: 1 test/234.397s/exit0. exact caller 검사를 유지하는 직접 반복문 수정 후 정상 fact parent→revision4/readback 경로가 통과했다. native log SHA256=c49cc27e20424537b3057fc262cdcba29635778152fa936f18587f19600809da.
- 현재 후보 sha256:83a4351856743aef0232a926f0ea2512aad7637f8dd94f89b11762dd7ad41279의 소유2/참조4·runtime 전후 불변. 이전 실패를 삭제하거나 새 후보의 전체 PASS로 바꾸지 않는다. 남은 matrix/최종 검증은 미실행이다.

## 중간 정적 검수 — FP-INTERIM-1 / FP-INTERIM-2

- 현상: 정상1건 PASS 이후 전체 context graph readback과 bridge 획득 경쟁 경계의 검증 누락을 fresh Critic이 정적으로 발견했다. native 실패나 race 재현을 실행했다고 주장하지 않는다.
- 처리: selected source와 full batch를 구분해 전체 보존 그래프를 non-dispatching으로 재확인하고, context 발급 사이 경쟁을 기존 발급 원장 안에서 차단한다. 동일 Coder 수리 대기, 아직 미해결.
- 근거: fivecircles/work/collaboration/eh-relay-20260907/messages/EH2.6.c4.2.b.3/004-first-parent-interim-review-1.json; main이 해당 호출경로를 직접 확인했다.

## 2026-09-07 23:29 KST — 중간 P1 수리 첫 실행 확인 실패

- 실제 결과: first-parent-selected-interim-repair-happy-1, 후보 sha256:58492ccbd1fa6d8870715ec4632016e4016f91403a40b5e5420e1b66ca5689ff, 1 test/46.397s/errors1/exit1. 소유 파일·runtime 전후 불변, postflight 문제0.
- 원인1: complete-context validator가 정상적으로 완료 cache를 다시 읽는데, 새 reservation 검사가 exact validator 경로를 아직 허용하지 않았다. controller_context_batch_reservation_required 발생.
- 원인2: Coder 보고에 따르면 초기화 hunk가 parent가 아닌 fusion claim 위치에 적용됐다. cleanup에서 batch_reservation_finished 미초기화 UnboundLocalError가 원래 오류를 가린 것은 main이 traceback으로 직접 확인했다.
- 조치: exact completed-validator read-only 경로만 결속하고 초기화를 함수의 고유문맥으로 올바르게 이동한다. cleanup/claim/reservation 실패 소비 회귀를 확인한다. 같은 경계 수리가 다시 실패하면 QUESTION으로 Design 재검토한다. P1 해결 또는 전체 PASS가 아니며, 이번이 중간 지적에 대한 첫 실행 확인 실패다.
- 근거: /private/tmp/eh-relay-20260907.GNy8vE/first-parent-selected-interim-repair-happy-1-result.json 및 .native.log; native SHA256=0284a3e357a5845499fb34ceb6fc5f88dd2757c46b868db7ffb5a8adec63af4e.

## 2026-09-07 23:36 KST — validator/초기화 실행 오류 재검사

- first-parent-selected-interim-repair-happy-2: 후보 sha256:3cba0d776a1aab896a0c40b6ec3d8d77c278e5544342729ef9f369b975884182, 1 test/234.958s/exit0, 소유 파일·runtime 전후 불변, postflight 문제0. main이 실제 결과와 원시 로그를 확인했다.
- 이번 PASS는 직전 validator/초기화 실행 오류의 정상 경로 재확인이다. FP-INTERIM-1/2 문맥 변경·경쟁 회귀와 전체 acceptance matrix/최종 검증은 남았으며 중간 지적 해결 완료나 batch PASS가 아니다.
- 근거: /private/tmp/eh-relay-20260907.GNy8vE/first-parent-selected-interim-repair-happy-2-result.json 및 .native.log, native SHA256=396645f4b3909062bfe7cafe01f01e044baccdfb4c1217d88170cf4157b9788c. 이전 실패는 그대로 보존한다.

## 2026-09-07 23:51 KST — 중간 P1 방어 회귀 확인

- 같은 후보 sha256:135492e729bac6330a00daf2fa337a0e87399f4fa02c9ea5594e3539d5a91f59에서 complete-context drift1/240.450s 및 parent+bridge acquisition races1/247.784s 모두 exit0. 파일·runtime 전후 불변, postflight 문제0; main이 원시 결과/로그를 직접 확인했다.
- FP-INTERIM-1/2에 대응하는 집중 회귀 근거가 생겼다. 최종 matrix/focused/adjacent/isolated/full과 fresh final deep이 남았으므로 최종 해결 승인이나 batch PASS로 표기하지 않는다.
- 근거: /private/tmp/eh-relay-20260907.GNy8vE/first-parent-selected-complete-context-drift-1-result.json, /private/tmp/eh-relay-20260907.GNy8vE/first-parent-selected-context-races-1-result.json. 이전 구현 실패/정적 검수는 그대로 보존한다.

## 개발 matrix 오류 분류 — 2026-09-08

- 실제 result: /private/tmp/eh-relay-20260907.GNy8vE/first-parent-selected-acceptance-matrix-1-result.json; raw log SHA 47d19119945b753812c77f7900460e02a15f82711049ec28ededb0a6430f2d5d. Main은 result와 전체 traceback을 직접 읽었다.
- 후보 sha256:a3b160d12761c3ebac5f0af73c587960fc0f0d90f329df12341d5f627815adea: native 8 tests/2782.645s/failures8/errors1/exit1, 파일·환경 불변/postflight0. top-level8과 subtest 실패 수를 합쳐 문항 수로 세지 않는다.
- 원인1: variants3은 semantic.owner_binding_sha256를 root bound.binding_sha256와 동일시한 신규 테스트 오류. 실제 factory는 retained RetrievalObligation.execution_binding_sha256에 결속한다(현재 source11553). 서로 다른 fingerprint 계약은 유지한다.
- 원인2: refusal2/prestarted1/mismatch1은 미청구 API 상태 pristine을 None으로 기대한 테스트 오류. source18714의 실제 계약 값을 확인했다. zero-call/claim 거절 검증을 제거하지 않는다.
- 원인3: max_rounds2는 config factory가 retrieval_rounds_not_pinned_to_one로 먼저 거절한다. 성공 fixture를 가정한 오류1 및 retained3!=4 연쇄 실패1. 더 이른 거절을 정확하게 검증한다.
- 정상 core·linked/bounds·동시 실행·등록 실패/재시도 금지 검사는 이번 실행에서 통과했다. 이것만으로 전체 또는 FP-INTERIM-1/2 final PASS를 선언하지 않는다.
- 수리: 동일 Coder가 소유 테스트의 fixture/기대값과 의미보존 line-event observer만 보완한다. guard/계약/기대 호출 수를 낮추지 않으며 새 후보에서 재검증한다. 반복 subcase3은 같은 attempt이고 수리 실패3회가 아니다.
- 운영 보완: 종료 후 원본 runner d309e272... bytes를 별도 보존하고 selected 개발 진단에만 -f 적용. 새 runner SHA bea23238dcf87b283b03786de7e2d24741830a645ab1d0367a383e5131092897; 실제 argv/요청·시작 IDs/미실행 요청/실제 count·exit/부분 subtest 한계 기록. final focused/adjacent/isolated/full 명령은 동일하다.
- Main helper 검증: 실제 upgrade exit0(a6c5c8), synthetic argv/parser/syntax exit0(b73f77). 제품 테스트 통과 수에 포함하지 않는다.
- 현재 새 selected 수리 실행 sha256:fbe089c30d62d76b6f39c4aac82507bb6aadeea709e3d3bce3b601cb4f32600f 시작 사실만 확인했다. 종료/통과 결과는 아직 없고 최종 freeze/통합 검증/검수도 미완료다.

## 선택 수리 확인 — first-parent-selected-matrix-repair-1

- 실제 2 tests/1077.629s/exit0, 파일·환경 불변/postflight0. 후보 sha256:fbe089c30d62d76b6f39c4aac82507bb6aadeea709e3d3bce3b601cb4f32600f.
- 원시 결과 /private/tmp/eh-relay-20260907.GNy8vE/first-parent-selected-matrix-repair-1-result.json; raw log SHA c3c1eff0e0757fcd0c6cd7386ab7922413540d1b167419358fa94f64db60f2cf.
- 이전 실패를 지우지 않는다. 선택 검사 통과이며 최종 focused/adjacent/isolated/full·fresh deep·통합 승인과 별개다.

## 선택 수리 확인 — first-parent-selected-matrix-repair-2

- 실제 3 tests/326.921s/exit0, 파일·환경 불변/postflight0. 후보 sha256:fbe089c30d62d76b6f39c4aac82507bb6aadeea709e3d3bce3b601cb4f32600f.
- 원시 결과 /private/tmp/eh-relay-20260907.GNy8vE/first-parent-selected-matrix-repair-2-result.json; raw log SHA ff0b301c8da9716748216b045d2334dbaa74899be3a3d3c79eb1c67fadb8a57e.
- 이전 실패를 지우지 않는다. 선택 검사 통과이며 최종 focused/adjacent/isolated/full·fresh deep·통합 승인과 별개다.

## 선택 수리 확인 — first-parent-selected-reservation-cleanup-1

- 실제 1 tests/99.013s/exit0, 파일·환경 불변/postflight0. 후보 sha256:7832be7a704c5f3b8a7a4c9d53beb7d02fd973f1b6de5d38bce58cbbb670bc2b.
- 원시 결과 /private/tmp/eh-relay-20260907.GNy8vE/first-parent-selected-reservation-cleanup-1-result.json; raw log SHA 9aa9eb9e7f2a3f9c0d764f47a14f4f7931e5f47929f39e49dbcf6d0f0b140824.
- 이전 실패를 지우지 않는다. 선택 검사 통과이며 최종 focused/adjacent/isolated/full·fresh deep·통합 승인과 별개다.
