# EH2.6.c3.5 effect non-authority 통합 리뷰

날짜: 2026-09-05
대상: `feat/total-integration`의 structural effect 비권한 경계와 기존 source validator authority
최종 판정: **APPROVE — P0/P1 없음**

## 검토 범위

- `ActionEffectReceipt`의 public/package consumer, issuer, registry와 all-`effect` module symbol inventory
- payload-free constant `repr`, constructor/copy/deepcopy/pickle/from-dict/subclass 차단
- equal-hash exact-class structural clone의 비권한성 및 state/terminal/citation 비승격
- lane/fusion/parent/bridge/rerank/semantic/absence 7종 validator의 receipt/dependency clone·mixed graph 거절
- 원본·대체 live graph 양쪽 provider 호출 불변과 API/model/Langfuse 호출 0

## 발견 및 수리

1. dataclass 기본 `repr`이 구조 해시와 evidence ID를 노출했다. constant redacted repr로 교체했다.
2. 고정된 몇 개 이름과 annotation만 보던 audit가 임의 이름의 consumer/registry를 놓칠 수 있었다.
   package export와 module의 all-`effect` symbol inventory를 exact allowlist로 봉인했다.
3. 단일 dependency만 섞은 테스트는 선행조건에서 먼저 실패해 최상위 receipt↔graph identity 결함을 놓칠 수
   있었다. 각 source family에 완성된 두 번째 live graph 전체 교체 공격을 추가했다.
4. 원래 runtime 로그만 검사하면 잘못 전달된 대체 runtime provider 호출을 놓칠 수 있었다. 원본·대체 그래프의
   dense/lexical/rerank/verifier 로그를 모두 고정했다.
5. 기존 source receipt authority와 미래 effect mint authority 책임 문구가 충돌했다. 기존 7종 source validator
   회귀는 c3.5, effect-side live dereference·decision permit·replay claim·mint/reducer는 d2/c4로 분리했다.

## 검증 증거

- focused effect contract/non-authority: 18/18 PASS
- 7종 source validator 관련 회귀: 147/147 PASS
- 전체 unittest: 1,288/1,288 PASS
- repository safety: 867 files PASS
- Mermaid/HTML Playwright: images 2, tables 8, page errors 0, mobile overflow 0 PASS
- 독립 재리뷰: APPROVE, P0/P1 없음
- 실제 API·OpenAI·model-provider·Langfuse 호출: 0

## 잔여 경계

- structurally valid effect와 기존 source validator 성공은 effect 실행 권한이 아니다.
- `HarnessExecution` aggregate는 d1, exact controller decision permit은 d2, effect mint/reducer는 c4에서 구현한다.
- 동일 golden 검색 성능 개선은 아직 미측정이다.
