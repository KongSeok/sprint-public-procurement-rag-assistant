# 두 검색 결과 뒤 다음 행동 선택 검수 — 2026-09-07

## Scope

- run=eh-relay-20260907 / batch=EH2.6.d2.x.b.1 / feat/total-integration.
- Sol Ultra 구현, fresh Astra post_lexical_critic_1 deep 검수. 메인은 JSON 결속·기록·통합 담당.
- 후보 sha256:0bf15494c562e632a378b6eeffe7e905a3d86bb5db7b246299f8060bb27364f5; 계약 sha256:a94c4e18105b63e71d93164ef7976c82bf0a2809adb2b06877e8691f67baa4ed; 증거 sha256:0b905e12be93d4fea487a2ae2d5cefddd958e67f846f5225d81092d438bacaf1.
- [원문 REVIEW](../collaboration/eh-relay-20260907/messages/EH2.6.d2.x.b.1/004-post-lexical-review-1.json).

## Findings

- 차단 지적 없음. exact lexical 전이와 보존된 dense predecessor 양쪽의 실제 source를 검증한 뒤 ordinal3 선택을 발급한다.
- 우선순위는 budget→contract error→provider error→fuse/기권. dense 오류는 lexical 성공으로 지워지지 않는다.
- 네 applied/empty 조합, both-empty·lexical-only rescue, 반복/동시/GC·변조 및 이전 결정 수명 보존을 확인했다.
- 추가 실행·claim 소비 없음. 실제 fusion 실행, semantic 승격, terminal 및 후속 compare obligation은 포함하지 않는다.

## Decision

APPROVE / REVIEW PASS. 집중11(105.314초), 관련105(83.978초), 격리132(192.425초), 전체1545(359.145초) PASS.
전체 실패/오류/skip0, exit0. 제품3파일·계약2파일 hash 전후 동일. Critic이 diff/전체 관련 코드/원시 로그/11개 증거 hash를 확인했다.
rubric 미설정으로 direction_score=null이며 판단 근거는 JSON에 있다. 합성 구현 검수일 뿐 실제 RAG 검색 품질 우승 판정이 아니다.

## Next actions

1. 같은 후보만 로그올·선택 통합. 부모 d2.x.b/Controller/E2E는 PARTIAL 유지.
2. 첫 obligation fuse 실행을 별도 Design으로 정의: exact revision2/ordinal3 permit, 양쪽 source, 1회 claim 소비, 실패 후 재시도 금지, revision3 readback.
3. context/rerank/verify/reducer/public API는 별도 후속. compare sibling 확대 전 canonical 수명 계약 필요.
4. 병렬 작업은 코드·데이터가 분리될 때만. 별도 승인된 retrieval 비교는 고정 snapshot/private 결과로 분리하고 latency 측정 중 무거운 테스트 중첩을 조정한다.
