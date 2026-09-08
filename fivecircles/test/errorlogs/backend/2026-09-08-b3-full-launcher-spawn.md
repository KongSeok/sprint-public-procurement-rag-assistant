# B3 전체 검증 실행기: multiprocessing spawn 재진입

- 발생: 2026-09-08, B3 후보49ff508f…의 v5 전체 검증. 제품 실행 오류와 구분한다.
- 증상: discovery1765에 비해 native ok 줄이 중복 증가했다. PDF 검사 직후 resolver-start와 첫 테스트가 다시 등장했다. raw resolver-start3회/result0회이며 최종 완료 건수는 없다.
- 원인: 고정 resolver가 최상위에서 suite를 실행하는데, launcher가 runpy의 __main__으로 올려놓았다. PDF의 multiprocessing spawn이 이 파일을 __mp_main__으로 재실행했다. Design과 별도 Critic이 코드·Python 런타임·로그를 대조했다.
- 조치: 소유 계보 확인 후 이번 full PID61248만 SIGTERM. tracker61393도 종료됐음을 확인했다. 집중·주변·격리 실행은 중단하지 않았다.
- 보존 결과: FAIL/SIGTERM, 671.212초, 요약 없음. INTERRUPTED_INVALID_DUPLICATED_SUITE로 해석하며 완료나 전체 PASS로 세지 않는다. 원시 로그 SHA256: 33f581cc42a5b5dc6e02558c41cbac9944656d2e3dd5d205563e8eb95d270c06.
- 원시 증거: /private/tmp/b3-resume-full-20260908.pgF42v/first-parent-resume-full-result.json 및 같은 prefix native.log.
- 수정 범위: v6 launcher의 run_name만 b3_frozen_analytics_driver로 변경했다. resolver SHA·제품·테스트·CSV·설치 환경·판정 기준은 그대로다. 차단된 LATENCY.FIX와 무관하며 해당 패치를 재시도하지 않았다.
- 선행 검증: 기존 실제 PDF 검사2개를 동일한 non-main runpy 구조에서 실행, 2/2 PASS·0.578초·exit0·start/result각1회·입력/환경 불변. /private/tmp/b3-resume-full-v6-20260908.76Hj46/spawn-preflight-result.json.
- 재검증: Design의 저장된 v6 ACK 후 새 full1회 시작. raw start/result도 각각1회여야 하며 모든 원래 discovery/실행/무결성/zero-skip 조건을 유지한다. 실패하면 재차 진단하며 자동 반복하지 않는다.
- 현재 상태: 실행기 좁은 재검증 PASS, 전체 검증 진행 중. 최종 B3 PASS는 아직 아니다.

재발 방지: multiprocessing을 실제 사용하는 suite를 임시 runpy로 실행할 때 __main__ 재구성을 점검한다. 처음에는 해당 spawn 검사로 실행 구조를 검증하고, 이벤트는 줄 시작에 한정하지 않고 중첩 출력까지 세어 중복 실행을 탐지한다.
