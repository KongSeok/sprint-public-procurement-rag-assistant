# KURE CPU 고정·가속기 사전 점검 누락

- 기록: 2026-09-07 15:50:01 KST. 사용자 요청: 사용 가능한 GPU를 놓친 장기 실측을 어레스트한다.
- 상태: 원인·환경 확인 및 재발 방지 기록 완료. GPU 모델 smoke·장치 전환·재실측은 미완료다.

## 발생·원인

- 전체131 검색 비교(129 질문×3검색=387회 모델 검색 시도)의 frozen retrieval_compare.py:302/308이 page/child KURE를 모두 device="cpu"로 생성한다.
  기존 retrieval_smoke.py:155/162의 CPU 설정을 재사용해 봉인했고, 장기 실행 전에 MPS 가용성·모델 smoke를 확인한 근거가 없다(실측 담당 확인).
- 장치 선택을 검토하지 않은 뒤 CPU 조건을 고정한 준비 오류다. CPU 실측의 재현성이 있다는 사실이 이 사전 확인 누락을 정당화하지 않는다.
  9월3일 MPS KURE 빌드 성공 기록도 있었으나 이번 실행 준비에 반영하지 않았다.

## 직접 확인한 근거

프로젝트 .venv의 Python에서 모델을 로드하지 않고 torch backend 가용성만 확인했다(2026-09-07 15:43 KST 기록).

| 동일 환경·명령 | MPS built | MPS available | CUDA available | 종료 |
| --- | --- | --- | --- | --- |
| 기본 sandbox | true | false | false | 0 |
| 승인된 host 실행 권한 | true | true | false | 0 |

- arm64 / torch2.13.0. 명령의 핵심은 torch.backends.mps.is_built(), is_available(), torch.cuda.is_available()이며 설정 변경·모델 로드·추론은 하지 않았다.
  제한 문맥의 false를 맥 하드웨어 미지원으로 단정할 수 없다. 권한 경계를 몰래 해제하거나 sandbox를 우회하는 지침이 아니다.
- frozen 생성자의 CPU 명시는 확인했지만, 진행 중 프로세스의 실제 모델 tensor를 외부 attach로 관찰한 것은 아니다.
  MPS 가용성도 이번 KURE 연산 성공·fallback 부재·속도 향상을 입증하지는 않는다.

## 영향·미확정 사항

- 사용 가능한 가속기 검토 없이 CPU로 장기 실측을 진행해 가속 선택 기회를 놓쳤다. 실제 지연과 사용자 대기 부담이 발생했다.
  다만 전체 지연 중 CPU 추론·검색/검증·I/O·동시 회귀의 기여도, 낭비 시간, MPS/CUDA 속도 배수는 아직 측정하지 않았다.
- 과거 9,496행 MPS 빌드와 이번 query embedding은 다른 작업이다. 과거 시간으로 이번 속도 향상을 계산하거나 CPU 결과 자체를 무효로 처리하지 않는다.

## 교정·종료 기준

- 어레스트 가드·테스트 정책에 아래 순서를 반영했다. 이 기록 작업에서는 실측 중단·장치 변경·결과 덮어쓰기를 수행하지 않았다.
  이후 실측 담당이 별도 사용자 승인에 따라 CPU partial 결과를 보존하며 중단·GPU 이관을 진행한다고 통보했다. 최신 상태는 실행 노트가 원천이며 여기서 이관 완료로 처리하지 않는다.
  현재 Controller 합성 테스트는 실모델을 사용하지 않으므로 이 이슈와 구분한다.
- 실측 담당의 기존 DIAG131.GCP에서 승인된 장치 파생 run의 실제 model/input device·최소 연산·fallback·receipt를 확인해야 한다.
  GCP L4 장착만으로 CUDA 사용이라고 보고하지 않는다. 장치 변경·재실행은 별도 설정/권한/새 출력으로 하며 CPU/GPU 지연을 같은 환경처럼 합치지 않는다.

## 재발 방지

1. 장기 모델 추론 전 기존 가속 실행 이력, 프로젝트 interpreter, 실제 worker의 device 설정과 전달 경로를 확인한다.
2. 실제로 허용된 실행 문맥에서 backend 가용성을 확인한다. sandbox 제약이면 근거를 구분하고 필요한 승인 절차를 따르며, 미지원으로 추정하지 않는다.
3. 모델 실행 권한 안에서 최소 대표 입력으로 모델/입력 장치와 실제 연산·CPU fallback을 확인한다. available=true 또는 설정 문자열만으로 GPU 사용 PASS를 내리지 않는다.
4. 선택 장치·dtype·batch·CPU 선택 이유를 실행 전에 기록/봉인한다. GPU 전제인데 CPU로 내려가면 조용히 장기 실행하지 말고 원인·대안을 확인한다.
5. warmup/load/query·I/O/채점 경계를 분리하고 비동기 가속 연산 완료를 반영해 시간을 측정한다. CPU 전용 unit test/BM25/무결성 검사에 GPU를 강제하지 않는다.

## 참조

- [실행 조건·이관 상태](../../../work/2026-09-07-mini131-retrieval-comparison.md)
- [기존 MPS KURE 실행 이력](2026-09-03-eh-rc0-evidence.md)
- [기존 CPU smoke 기록](2026-09-06-retrieval-smoke-runtime.md)
- [가속기 사전 점검 정책](../../testpolicy.md#model-accelerator-preflight-2026-09-07)
- 직접 확인의 원시 요약: /private/tmp/eh-relay-20260907.GNy8vE/device-check-20260907.json. 공개 로그에는 키·질의·원문을 복제하지 않는다.
- 별도 Astra의 사실·가드 범위 교차확인 완료. 이는 제품 후보 REVIEW PASS나 실제 GPU 실행 검증이 아니다.
