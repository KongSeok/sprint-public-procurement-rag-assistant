# EH2.6.b3 검색 의무·독립 레인 실행 리뷰

날짜: 2026-09-04
대상 브랜치: `feat/total-integration`
판정: **APPROVE — P0/P1 없음**

## 검토 범위

이번 leaf는 `BoundFact`와 `BoundCompare`에서 검색 의무를 발급하고, dense와 lexical 검색을 서로
독립된 실행 영수증으로 남기는 기반을 구현했다. fusion, E0 aggregate, 생성과 실제 모델 품질 평가는
각각 EH2.6.b4 이후 및 평가 단계의 책임으로 남겼다.

주요 계약은 다음과 같다.

- raw query와 qrels를 공개 obligation·receipt에 넣지 않는다.
- query, scope, budget, evidence store, execution config와 runtime identity를 호출 전에 검증한다.
- 전체 obligation 순서에서 각 dense→lexical 레인을 정확히 한 번만 소비한다.
- provider failure와 호출 전·후 contract failure를 구분하고 `call_performed`를 실제 경계에 맞춘다.
- dense provider failure 뒤 untouched lexical을 한 번만 진단 실행한 뒤 종료한다.
- text evidence는 store-local locator hash와 chunk-invariant source-block join hash를 함께 보존한다.
- request graph가 수거되면 issuance·obligation·ledger·permit·receipt authority도 정리한다.

## 독립 리뷰에서 발견해 닫은 문제

초기 구현은 ledger/authority 상태를 함께 되돌리거나 내부 `_claim`·`_close`를 직접 호출하면 실제 검색
없이 영수증을 만들 여지가 있었다. 다음 보강으로 닫았다.

- ledger state를 private mirror, revision, 이전 state hash로 봉인했다.
- lane close마다 한 번만 쓸 수 있는 transition permit을 발급하고 receipt mint에서 소비한다.
- ledger mutation을 public executor code에 closure-sealed하여 module-global spoof와 direct 호출을 거부한다.
- forged permit, permit 재사용, receipt/authority 동시 변조를 회귀 테스트로 고정했다.
- owner module/class/function, runtime class/method/config/store identity를 호출 전에 검증한다.
- weak-reference cleanup을 넣어 query와 request graph가 장기 서버 registry에 남지 않게 했다.

최종 독립 재리뷰는 direct claim/close, caller-global spoof, forged/reused permit, 정상 receipt 검증,
source-block join, qrels 비노출, request graph GC를 다시 확인하고 P0/P1 없음으로 승인했다.

## 검증 결과

```text
PYTHONPATH=src .venv/bin/python -m unittest tests.test_retrieval_obligations -q
Ran 36 tests — OK

관련 집중 회귀
Ran 186 tests — OK

PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -q
Ran 1147 tests — OK

bash scripts/validate_repo_safety.sh
Repository safety check: PASS (823 files scanned)

git diff --check (대상 파일)
PASS
```

테스트는 합성 lane만 사용했다. OpenAI API, Langfuse, 로컬 임베딩·생성 모델과 외부 provider 호출은
실행하지 않았다.

## 다음 단계

다음 READY leaf는 `EH2.6.b4`다. 같은 round의 정상 dense·lexical receipt만 pure RRF로 합칠 수 있는
`FusionReceipt`와, 상태 전이 없이 한 번 실행되는 E0 control aggregate를 구현한다. 사람 검토가 필요한
gold/qrels 보강은 병합된 `EH2.EVAL.4`에서 병행하되 runtime 입력과 분리한다.

## 재개 후 최종 판정 보충 — 2026-09-05

최초 승인 뒤 exact code object를 재사용하면서 globals만 복사한 executor clone 가설이 새로 제기되어
b3 완료 판정을 일시 철회했다. ledger mutation caller가 issued executor의 exact code뿐 아니라 exact
module-global namespace에서도 실행됐는지 검사하도록 보강했고, clone은 provider 호출 0회로 거부된다.

b4를 연결하면서 다음 obligation의 lane은 이전 obligation fusion이 끝난 뒤에만 열리도록 순서 gate도
추가했다. b3+b4 양방향 순서 반복 64/64, 관련 회귀 214/214, 전체 1,175/1,175 PASS와 b4 독립 최종
재리뷰를 근거로 b3의 재개 상태를 다시 **COMPLETED**로 닫는다.
