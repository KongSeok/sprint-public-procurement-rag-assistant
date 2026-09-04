# EH2.6.c1 follow-up E1 projection 독립 리뷰

날짜: 2026-09-05
브랜치: `feat/total-integration`
판정: **APPROVE — P0/P1/P2 없음**

## 검토 범위

- 전용 public boundary `build_e1_followup_harness_state`
- 기존 EH2.5 compatibility builder/replay 비변경
- follow-up primary/fallback 후보의 E1 candidate 투영
- metadata fail-closed, retrieval 0회, gold/evaluator 비누출
- exact outcome/store 권한과 finite runtime-integrity threat boundary

## 확인 결과

- EH2.3의 verified ID는 모두 candidate로 강등된다.
- primary 후보 뒤 optional fallback 후보가 first-seen 기준으로 중복 제거된다.
- `$answer_support`에는 전체 후보, 실제 required slot에는 같은 sealed-store `doc_id` 후보만 들어간다.
- 모든 obligation은 open, coverage는 0, normal stop과 abstain은 false로 시작한다.
- metadata predicate는 EH3.1 filtered-scope receipt가 없으므로 fail-closed한다.
- public signature는 `bound, outcome, store, registry, policy`만 받고 추가 retrieval을 실행하지 않는다.
- equal-looking outcome/store clone, 발급 후 drift, public dependency alias와 단일 private pin/registry drift를 거부한다.

## 리뷰·수리 이력

1. mutable validator global을 trust root로 함께 쓰던 문제를 closure-private module snapshot으로 분리했다.
2. validator code/default/internal dependency drift와 direct implementation alias 우회를 차단했다.
3. outcome authority를 동일 immutable record를 공유하는 primary/mirror map으로 봉인했다.
4. public validator alias와 private module pin 하나를 함께 바꾸는 조합을 same-object pin mirror로 차단했다.
5. 여러 private closure/registry를 동시에 패치하는 arbitrary in-process code 실행은 Python sandbox 비범위로 계약에 명시했다.

## 검증

- focused: `tests.test_e1_followup_projection` 7/7 PASS
- related: c1 + EH2.5 state/action + follow-up authority 60/60 PASS
- full: unittest discover 1,186/1,186 PASS, failure/skip 0
- repository safety: 837 files PASS
- 독립 리뷰: contract, adversarial, authority 세 관점 모두 최종 APPROVE
- 실제 API/model/Langfuse 호출: 0

Mermaid PNG는 재생성·직접 검사했다. HTML browser visual QA는 local file URL 정책으로
environment-blocked이며 우회하지 않았고, 로컬 자산/상태 참조만 정적으로 확인했다.
