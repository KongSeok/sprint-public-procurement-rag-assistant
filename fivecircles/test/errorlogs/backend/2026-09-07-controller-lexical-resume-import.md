# Controller lexical 재개 시 import 실패

- 시각: 2026-09-07 11:40 KST
- run_id=`eh-relay-20260907`, batch_id=`EH2.6.c4.2.a`.
- 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest tests.test_controller_lexical_transition`.
- 결과: exit1, 테스트 수집 전 TypeError. 기존 미완성 초안 factory의 새 필수 의존성8개가 호출부에 연결되지 않음.
- 증거: `/private/tmp/eh-relay-20260907.GNy8vE/baseline-focused.log`.
- 처리: Coder가 기존 계약 안에서 wiring·반환 binding을 완성하고 집중/관련/전체 검증. 해결 여부는 재검증 후 기록.
- 경계: 이전 완료 커밋의1511/1522 테스트 회귀와 혼동하지 않는다. 현재 미커밋 초안의 재개 실패다.

## 중간 확인

- 2026-09-07 11:48 KST: 격리한 HEAD34f80c5의 initial/next-decision24 PASS(18.405초, exit0).
- 코더 wiring 후 import exit0. 첫 동작검사는29건·failure2·error56로 실패했다(7.571초).
- 이 수치는 subTest/정리 단계 오류를 포함한 unittest 출력이다. 별개의58개 결함이라고 해석하지 않는다.
- 근거: 같은 임시 디렉터리의 `committed-baseline.log`, `import-after-wiring.log`, `focused-after-wiring.log`.
- 상태: 기능 수리·재검증 중. 최종 통과 결과와 원인/수정은 검증 후 보완한다.

## 최종 해결 — 2026-09-07 12:27 KST

- 원인: 인자 연결 후에도 authority seal이 closure를 바꾸기 전에 dependency pin을 캡처해 기존 전이 검증이 불일치했다.
- 수정: factory wiring/반환 binding 완성, 공유 advance 경로의 실제 mint caller 결속, 모든 seal 이후 pin 최종화.
- 재검증: 초기 lexical5 PASS → 집중29 PASS → lexical12/집중36/관련98/격리134/전체1534 PASS.
- 전체1534는279.294초, 오류/실패/skip0, exit0. 후보/계약5개 해시 전후 동일, fresh Astra PASS.
- 상태: RESOLVED. 원시 실패 기록은 유지하고 테스트 통과로 원래 실패를 덮어쓰지 않는다.
