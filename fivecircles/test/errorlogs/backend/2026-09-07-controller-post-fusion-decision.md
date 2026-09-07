# Post-fusion 결정: 최소 RED 및 round-cap 계약 충돌 — 2026-09-07

## Scope

run=eh-relay-20260907, batch=EH2.6.d2.x.b.2, initial directive=post-fusion-directive-1.

- 기록 재확인: 2026-09-07 19:06:21 KST. 아래 과거 실행의 정확한 시작 시각은 별도 수집하지 않았으며 이 시각으로 대체하지 않는다.

## 최소 RED (예상 TDD)

- 명령: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.test_controller_post_fusion_decision.ControllerPostFusionDecisionTests.test_applied_fusion_selects_first_bounded_parent_seed
- 결과: native output 1 test/19.217s, errors1; Coder가 process exit1을 보고했다. main은 실제 native 파일을 읽었다.
- 원인: 실제 revision3 이후 _d2_controller_action_plan이 controller_decision_cross_state_not_ready를 발생시킨다. 새 기능의 예상 RED이며 기존 제품 회귀나 PASS가 아니다.
- 증거: /private/tmp/eh-relay-20260907.GNy8vE/post-fusion-focused-red-1.native.log; SHA256 2d223dbf6b7d29de4adbdc92d247b6d49409df0483c8a635a992b340d6e10324.

## 계약 충돌 (Coder QUESTION)

- 증상: 새 지시/계약이 round cap1/larger의 정상 성공을 요구하지만 기존 _validate_config_values는 !=1을 거부한다.
- 영향: config 확장은 금지돼 있어 larger-cap 성공을 구현하면 범위를 벗어난다. 해당 테스트와 최종 동결을 보류했다.
- 권고: 기존pin1 유지, 정상round1 및 round2 시도 zero-dispatch 거부를 검증한다. 아직 Design 결정을 미리 승인한 것으로 기록하지 않는다.
- 메시지: ../../../work/collaboration/eh-relay-20260907/messages/EH2.6.d2.x.b.2/002-post-fusion-round-cap-question-1.json.
- 상태: WAITING_GUIDANCE. 별도 complete updated DIRECTIVE가 필요하다. 안전한 독립 round1 구현만 허용한다.

## 재발 방지 / 후속

기술 문서의 future ceiling 설명을 현재 config 지원으로 추정하지 않는다. 실제 validator·설정 생성자와 테스트 가능한 입력 범위를 계약 작성 때 함께 확인한다. 코드·설정 우회로 테스트만 통과시키지 않는다.

## Design 해결 및 main 확인

- post-fusion-directive-2가 option A를 ACCEPT했다. 기존 validator/§16.10과 일치하며 larger-cap 정상 성공 요구는 Design 오류였다.
- 기존 round1 설정과 코드 제약은 그대로 둔다. round2는 생성/dispatch 전에 거부되는지 검증한다. config 확대·테스트 우회는 없다.
- 메인은 실제 validator/기존 테스트와 두 계약 변경 부분을 대조하고 설치된14930bytes/hash를 확인했다. 기존001 이벤트·RED 증거는 보존한다.

## 중간 repair의 실행 관찰 누락

- 동일 최소 테스트의 native log는 1 test/38.009s 및 OK다. main도 실제 파일을 읽었다.
- Coder는 tool이 30초에 yield할 때 session_id를 출력하지 않아 실제 process exit을 회수하지 못했다고 보고했다. exit_code=null(unknown)로 취급하며 최종 필수 PASS로 쓰지 않는다.
- 로그: /private/tmp/eh-relay-20260907.GNy8vE/post-fusion-focused-repair-1.native.log; SHA256 48194fc22f8ef6030e1ef24a4b6eea9e3640d9aba8530ef7a2e10c35d152298f.
- 조치: 최종 focused/adjacent에서는 exec 반환값·session_id·완료 exit을 회수하거나 child close 결과를 고유 JSON에 저장한다. 코드/계약/input의 시작·종료 hash도 함께 보존한다.
- 이 중간 실행을 증거 포장용으로 반복하지 않고 계획된 최종 동결 검사로 검증한다. OK 출력만으로 exit0을 추정하지 않는다.

## compare 경로 구현 검증 실패 — 2026-09-07 19:20:09 KST 기록

- native 결과: 6 test methods/642.812초, FAILED(errors=5). Coder가 actual process exit1을 회수해 보고했고 main은 native 122줄을 직접 확인했다. 다섯 error는 네 compare lane 조합과 compare 동시 호출 테스트다.
- 오류: 새 _d2_post_fusion_action_plan에서 controller_decision_fusion_transition_required. 비교 계획과 검색 이력 fingerprint 대조를 Coder가 진단 중이다. 확정된 원인/해결로 아직 기록하지 않는다.
- 증거: /private/tmp/eh-relay-20260907.GNy8vE/post-fusion-focused-repair-3.native.log; SHA256 794f23d55ba1ee192c1d75e1acf9468ccb9f3a1a9a7b3bb5b039d9a0f430e575.
- 정확한 6-method 명령은 아래와 같이 Coder의 실제 회신으로 수신했다. 기록을 위해 다시 실행하지 않았다. stdout/stderr는 위 native 파일로 합쳐 수집했다.

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.test_controller_post_fusion_decision.ControllerPostFusionDecisionTests.test_fact_compare_all_normal_pairs_bind_state_and_choose_first_action tests.test_controller_post_fusion_decision.ControllerPostFusionDecisionTests.test_repeated_and_barrier_concurrent_calls_return_one_exact_object tests.test_controller_post_fusion_decision.ControllerPostFusionDecisionTests.test_gc_tombstone_prevents_remint_while_snapshot_is_live tests.test_controller_post_fusion_decision.ControllerPostFusionDecisionTests.test_clones_mixed_graphs_and_unsupported_later_snapshot_fail_closed tests.test_controller_post_fusion_decision.ControllerPostFusionDecisionTests.test_source_state_owner_effect_transition_and_ledger_drift_fail_closed tests.test_controller_post_fusion_decision.ControllerPostFusionDecisionTests.test_reason_action_target_and_equal_value_tuple_drift_fail_readback
```
- 구분: 새 기능의 구현 검증 실패이며, 의도된 최초 minimal RED와 별도로 보존한다. 기존 baseline 전체가 회귀했다고 단정하지 않는다. 현재 범위 수리는 허용하지만 동결/PASS/통합/다음 의존 배치는 보류한다.

## 최소 수리 및 evidence helper 목록 불일치 — 2026-09-07 19:34:21 KST 기록

- Coder 최소 compare 수리1/114.237초 OK, actual exit0. main이 native log를 확인했다: /private/tmp/eh-relay-20260907.GNy8vE/post-fusion-focused-repair-4.native.log (SHA256 d48fab4b8fd151de853b8b04f73f73ad634a1e128601cd2baa37df3210664269). 모든 compare 경우의 최종 통과를 의미하지 않는다.
- 보고된 실제 수리 원인은 base/effective plan의 과도한 직접 동일성 조건이다. 별도 Design의 query 의미 구분 확인을 이 실패의 직접 원인 판정으로 바꾸지 않는다.
- main 최종 캡처 helper가 이전 intake의 first-fusion 계약 대신 module-contract를 포함한 두 파일을 가리켰다. Coder가 실행 전에 발견하여 final 검사 시작을 보류했다. 이 문제로 수행·실패한 final test는 없다.
- 완전 v3 지시는 세 참조를 모두 캡처하며 기존 계약 본문/ID·제품 범위를 보존한다. main이 모든 helper/collector를 함께 정렬하고 수락을 기다린다. 기록 원천: messages/EH2.6.d2.x.b.2/004,005.

## 수리 후 최종 집중 검사 — 2026-09-07 19:58:49 KST 기록

- 전체 focused11/904.510초 OK, actual child/helper exit0. 제품3·계약참조3 및 runtime 전후 동일. main도 native log/hash/현재 파일을 확인했다. compare 오류 및 helper 목록 정정 후의 새 실행이며 과거 실패/unknown exit는 덮어쓰지 않는다.
- 결과 원천은 위 배치 폼의 final focused1 receipt. 인접/전체/격리 검사와 fresh REVIEW 전이므로 배치 전체 완료는 아니다.

## Main 전체 회귀의 frozen CSV 불일치 — 2026-09-07 20:37:02 KST

- 실제 결과: full1657 /1672.755초 /errors1, failures0, skipped0, native child/helper exit1. 원래 명령과 native 로그는 post-fusion-full-result.json에 보존했다.
- 유일 ERROR: tests.evaluation.test_corpus_analytics_baseline.CorpusAnalyticsBaselineTests.test_frozen_refined98_snapshot_recomputes_all_gold_fields. _load_and_bind_inputs에서 refined_csv_sha256_mismatch, 계산 전 중단이다.
- 기대 cef0a276…와 canonical7c5a9b76… 불일치. 보존 CSV 사본은 기대값과 정확히 일치한다. 현행 CSV 변경 주체/내용은 이번 검사 범위 밖이다.
- 후보6파일·명시된 코드/테스트 입력·runtime 전후 동일. 원시 artifact SHA e420a617e901eb22787344b5fbf1d7d2d586a999cb644a4b28ef0e5f83dc433d. private 파일 전체의 전후 동일성을 확보했다고 주장하지 않는다.
- 조치: 원본/gold/기대 hash/코드/assertion 변경 없이 완전 Design 입력-resolver 지시를 요청한다. native full은 FAIL로 유지하고 임의 skip/예외 PASS/새 의존 배치 진입은 하지 않는다. 격리 검사는 아직 별도 실행 중이다.

## 입력 회복 실행기 수리 대기 — 2026-09-07T12:08:09.767Z

- 실제 Coder가 완전 v4를 읽고 수락했다. 제품3/계약3은 계속 동결한다.
- 계측 preflight 2건과 진단 probe 1건의 실패를 보존했다. 현재 두 probe는 기존95/96 관측값을 재현하지만, 과거 metadata probe의 상속 PYTHONPATH는 UNKNOWN이다. 단순 중복제거나 과거 환경 복구로 해석하지 않는다.
- 최초 회복 실행은 exit1, 실제 검사0개다. 임시 Python 파일 직접 실행 시 tests 패키지가 sys.path에서 빠져 discovery 단계가 실패했다. 이것은 analytics5의 실패/성공 결과가 아니며 원래 full1657 ERROR1은 그대로다.
- 고정 resolver 내용/데이터/정답은 바꾸지 않은 채 launcher 수정의 완전 후속 지시를 요청했다. 원래 실패 산출물은 덮어쓰지 않는다. 결합 판정은 PENDING_REVIEW.

## 회복 2차 완료 / fresh deep 검수 대기 — 2026-09-07T12:32:34.655Z

- 실제 Coder가 완전 v5를 읽고 수락했다. main의 exact -c/runpy launcher에서 tests/product origin을 확인했고, analytics5/0.073초/OK/child·helper exit0, 전후 무결성 문제0이다.
- 원래 full1657 ERROR1과 첫 회복 discovery FAIL(실제0)을 보존한다. canonical CSV는 바꾸지 않았고 여전히 동결 해시와 다르다. 중복4개가 있으므로 1662개로 합산하지 않는다.
- focused11·adjacent205·isolated216 PASS 및 원래 v3 파일/계약/입력 증거를 41개 산출물 manifest에 결속했다. 새 증거 sha256:eaf054ab203e73671d84ba9f9b035bbcaf45027f12bb6c8c21a7e331c8366771; 현재 결합 판정은 PENDING_REVIEW다.
- 현재 두 환경 probe는95/96관측을 정확히 재현했으나 과거 상속 PYTHONPATH는 UNKNOWN이고 과거 import-origin/전체 dependency 바이트는 수집하지 않았다. fresh deep이 이 한계를 포함해 적합성을 별도 판정한다.
- 실제 v5 IMPLEMENTATION_REPORT를 수락했다. REVIEW_READY는 합격이 아니며 제품/계약은 동결한다.

## 최종 독립 판정 — 2026-09-07 21:41:07 KST

- 집중11·관련205·격리216 PASS. 원래 전체1657은 CSV 동결 해시 오류1로 FAIL; 동결 사본 analytics5 재검증 PASS 및 fresh deep의 증거 결합 승인.
- COMPOSED_VALIDATION_PASS는 단일 전체 실행 PASS가 아니다. canonical CSV는 UNREPAIRED이며, 중복 검사를 더해1662개로 세지 않는다. 과거 metadata probe의 상속 PYTHONPATH는 UNKNOWN으로 보존하고 현재 관측 재현의 한계를 독립 검수했다.
- 과거 오류를 삭제/성공으로 변경하지 않는다. 현재 Controller 후보에 미해결 차단 지적0; canonical 입력 관리 문제는 별도 경계로 남는다.

## 현재 공개 검사와 좁은 재판정 — 2026-09-07T12:53:08.527Z

- 공개 안전 검사: native FAIL/exit1은 이전 합성 해시 두 필드의 변함없는 숫자 패턴이다. 이번 검토 payload46에는 개인정보/키 패턴0이며 post-fusion-publication-review-1가 실제 범위를 검수했다. 일반 해시 면제나 자동 검사 PASS가 아니다. 최종 추가 기록/경로/hash는 통합 영수증에서 별도 대조한다.
