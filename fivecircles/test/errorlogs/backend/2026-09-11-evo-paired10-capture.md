# 같은10문항 OFF/ON — 실행 실패와 추출기 수정

기록: 2026-09-11 00:44 KST. run `paired10-c38-20260911-001`.

## 추출기 오류 — 수정 완료

- 증상: OFF4번 `capture count mismatch`. completed search3개 중1개가 `duplicate:true`, 실제 검색 capture는2개였다.
- 원인: 기존 exporter는 empty_scope만 제외하고 에피소드 캐시 반환을 실제 backend 호출로 잘못 셌다.
- 수정: capture 결속 시 duplicate와 empty_scope를 제외한다. 원본 actions에는 캐시 행동을 그대로 보존한다. 첫 검색 순위·정답·모델 코드는 바꾸지 않았다.
- 확인: OFF/ON 각21개 허용 projection 보관·원본/사본 hash 확인, 같은10개 ID·환경·호출별 adapter 격리 일치. 기존 scorer 실행 성공. 모델 재실행0.

## 런타임 실패 — 비교 결과로 보존, 이번에 수정하지 않음

- OFF2·7: `finish_evidence_status_mismatch`로 invalid_action_limit. OFF9: policy_attempt_budget_exhausted. OFF10: policy_context_budget_exceeded.
- ON2: `invalid_final_answer`. 최종 답변 생성1회 후 오류이며 의미 답변으로 재구성하지 않았다.
- 결과: 실패 문항4→1, 잘못된 행동4→0. 런타임 안정성 변화이며 의미 정답 통과는2→2로 동일하다.

## 운영·재발 방지

- checkpoint38 실행파일5개 전송은 목적지·payload에 대한 사용자 명시승인 후 진행했다. 기존 학습·서비스·메인 소스·기존 결과는 보존했다.
- OFF/ON 답변은 같은 문항을 각각 새로 생성한다. 모델/데이터 조건이 다른 과거 응답을 학습 효과 비교로 섞지 않는다.
- 검색 @k의 측정 분모가 다르면 공통 관측 문항을 따로 비교한다. 본문 없는 응답에는 의미점수를 만들어 넣지 않는다.

보고: `fivecircles/work/2026-09-11-evoTrained1-paired10-comparison.md`.

## 추가 보고서 복사 — 차단 이력 / 후속 승인으로 해결

2026-09-11 00:51 KST, 내부 평가·환경 정보가 포함된 집계 보고서의 VM 루트 복사는 별도 명시승인 부족으로 자동 심사에서 차단됐다. 우회·재시도하지 않았다. 로컬 보고서/채점/원래 VM 실행 결과는 정상 보관됐고, 보고서 추가 사본만 미전송이다.

후속 사용자 명시승인 후 복사 완료. `/home/pio/evo35-cuda-test-20260910/paired10-c38-20260911-001-report.md`, 9,179bytes, 로컬/VM SHA256 `8ca729c18db992314483af0a2a70f97ca278b9836bd09c2f976591dd47afcb2e` 일치. 위 문단은 차단 당시 상태이며 현재 미전송 상태가 아니다. 모델·원문·가중치·서비스 변경은 없었다.
