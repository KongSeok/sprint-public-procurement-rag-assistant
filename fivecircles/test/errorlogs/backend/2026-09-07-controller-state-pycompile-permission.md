# Controller 상태 모듈 문법 확인 — py_compile 캐시 쓰기 제한

- 기록: 2026-09-07 17:01 KST. run=eh-relay-20260907 / batch=EH2.6.c4.2.b.2.
- Coder 보고: 탐색용 py_compile가 exit1로 끝났다. 전체 인자는 최종 구현 보고로 수신했으며 기록을 위해 다시 실행하지 않았다.

```text
python_path=.venv/bin/python3; "$python_path" -m py_compile src/midprojectrag/orchestration/harness_state.py src/midprojectrag/orchestration/execution_contracts.py tests/test_controller_first_fusion_state.py tests/test_controller_first_fusion_transition.py
```

## 확인한 오류·처리

- Operation not permitted: src/midprojectrag/orchestration/__pycache__/harness_state.cpython-312.pyc.4397979568. 제품 문법 오류가 아니라 저장소 캐시 쓰기 권한 오류다.
- 이 검사를 후보 PASS 증거로 사용하지 않았다. 이후 직접 redirect한 required focused25 및 고정 격리227은 정상 수집·실행·PASS했고, 전체 검증은 별도로 진행한다.

## 예방·증거

- 일반 import 검사는 PYTHONDONTWRITEBYTECODE=1을 유지한다. 명시적 py_compile의 출력 쓰기는 이 환경 변수로 막히지 않으므로 필요하면 파일을 만들지 않는 compile(source, path, 'exec') 방식으로 확인한다. 이 대안의 실행 성공을 소급 주장하지 않는다.
- Coder가 보존한 출력 전사: /private/tmp/eh-relay-20260907.GNy8vE/first-fuse-state-pycompile-sandbox-failure.log; SHA256 f2e3f3391a1f3271f29ba6a656cf038b81a9b75cbde4d4e956dcd50fe92a0419.
- [배치 폼](../../../work/2026-09-07-controller-fusion-state-relay.md). 모델/GPU 실행 이슈와 별개이며 권한을 우회하거나 assertion을 완화하지 않았다.

## 최종 확인 — 2026-09-07 17:21 KST

- 집중25(779.422초)·관련202(230.049초)·격리227(944.217초)·전체1611(1161.717초) PASS, 실패/오류/skip0, exit0. fresh Astra first-fuse-state-review-1 PASS. 원래 실패·탐색 전사본은 보존하며 최종 실행과 혼합하지 않는다.
- 이 오류는 현재 후보의 미해결 필수 실패가 아니다. py_compile 대안을 실행한 것으로 소급 기록하지 않는다.
- [최종 배치 기록](../../../work/2026-09-07-controller-fusion-state-relay.md).
