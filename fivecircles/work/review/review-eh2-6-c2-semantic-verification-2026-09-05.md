# EH2.6.c2 semantic verification 최종 리뷰

날짜: 2026-09-05
대상: `feat/total-integration`의 c2 semantic obligation/request/normalizer/execution/receipt
최종 판정: **APPROVE — 남은 P0/P1/P2 없음**

## 검토 범위

- fact/compare/follow-up exact owner에서 target·query·supplied evidence를 유도하는가
- verifier request/result가 닫혀 있고 public/gold authority를 받지 않는가
- exact `verify(self, request)` one-call, unavailable zero-call, local at-most-once가 유지되는가
- provider 반환 뒤 source/prerequisite/store/config/runtime/action normalizer를 재검증하는가
- typed value/support/contradiction과 state-free receipt가 계약대로 봉인되는가
- receipt GC와 source lifecycle, 동시 실행, clone/mixed dependency, 직렬화·비누출 경계를 검증하는가

## 발견 및 수리

| 등급 | 발견 | 수리·회귀 |
| --- | --- | --- |
| P1 | semantic execution history가 source 종료 뒤에도 남아 메모리 증가와 object ID 재사용 오판 가능 | source weak lifetime별 execution key cleanup 추가. receipt GC 중 replay 차단과 source GC 뒤 history 정리를 한 테스트에서 검증 |
| P2 | private verifier request/evidence 일반 constructor가 열려 있음 | token factory-only constructor로 변경, 직접 생성 거부 |
| P2 | constructor를 닫아도 pickle/copy protocol이 객체를 재구성 | `__reduce__`/`__reduce_ex__` fail-closed, pickle/copy/deepcopy 거부와 class pin 추가 |
| P2 | semantic call graph의 schema/validator/Unicode attribute pin 누락 | reachable constant/function/module attribute pin과 pre-call zero-dispatch 회귀 추가 |
| P2 | receipt mint 전 completion 전환 | mint/register 성공 뒤 completed 전환, 실패 시 sanitized failed-consumed로 변경 |
| 계약 명료화 | bad ABI가 preflight인지 consumed attempt인지 문구가 모호 | ABI/identity 거부는 zero-call·미소모, 호출 뒤 provider/result/drift만 attempt 소비로 계약·반복 테스트 일치 |

## acceptance 보강

- private request raw owner query, contiguous index, candidate order, evidence ID 비노출, 직렬화 API 부재
- supported/unsupported/contradicted/unavailable 실제 receipt 발급·검증
- follow-up 실제 field slot typed value와 source state 불변
- verifier callback 중 dependency drift의 sanitized error·재시도 차단
- 다른 source의 fusion receipt, empty candidate의 factory zero-call 거부
- 성공 receipt GC 뒤 replay 차단과 source 수명 종료 cleanup
- public factory/executor의 raw authority/varargs 부재와 obligation payload allowlist
- schema/disposition/value shape/index/promotability negative matrix

## 검증 증거

- focused: `tests.test_action_effects tests.test_semantic_verification` → 26/26 PASS
- related: execution/retrieval/fusion/follow-up/action/semantic → 118/118 PASS
- full: `unittest discover -s tests -q` → 1,212/1,212 PASS
- safety: 846 files PASS
- flow HTML: images 2, tables 8, page errors 0, mobile overflow false
- 실제 API/OpenAI/model/Langfuse 호출: 0; synthetic verifier만 실행

두 독립 최종 재리뷰가 모두 APPROVE를 반환했다. 이는 구현·무결성 수용 판정이며, 동일 골든셋 기반
검색 성능 향상이나 최종 아키텍처 승리 판정은 아니다.
