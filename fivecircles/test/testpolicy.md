# Test Policy

## Development Cycle Alignment

This policy belongs to the Test phase of the development cycle
(Requirements, Design, Implementation, Test, Maintenance).

## Mandatory Pre-Test Check

- (See work/workpolicy.md) This check is required before implementation begins.

## Scope

- Applies to local runs, CI runs, and ad-hoc manual testing.
- Does not change product behavior; it prevents repeatable test failures.

## Local Python Runtime (2026-09-06)

- Run from `/Users/pio/Documents/AIENGINEERCOURSE/MidProjectRAG` with `.venv/bin/python` (current Mac: Python 3.12).
  Check the existing venv before diagnosing dependencies as missing; bare `python` may select Miniconda 3.13.
- Provision full-suite extras using the README installation command; base `pip install -e .` is insufficient.
  Preserve `requirements/gcp-local-lock.txt` pins on this macOS/arm64 runtime and run `.venv/bin/python -m pip check`.
- Full regression command:

  ```bash
  PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
    .venv/bin/python -m unittest discover -s tests -t . -p 'test*.py'
  ```

- Focused runs use the same interpreter and `tests.*` module names. `-t .` keeps fixture imports consistent.
- `.index.lock` and macOS `sandbox-exec` integration checks require their actual OS permissions.
  Rerun affected tests with available permissions; do not weaken assertions or count blocked checks as PASS.
- Record the unittest summary, process exit status, skips and reasons. Module import failures can hide additional
  test cases, so a repaired environment may collect more cases than the failing run.

## Log Formatting (Mandatory)

- Every test error log must include a timestamp (local date and time).
- Write each error summary as a separate text file under `test/errorlogs/`.
- Separate backend and frontend logs into `test/errorlogs/backend/` and `test/errorlogs/frontend/`.
- After tests, record error logs and fixes in the appropriate folder.
- When an error is resolved, record the resolution in `test/learn-from-log.md`.

## Token-lite Logging (Default)

- Keep error logs concise and avoid duplicating long explanations from update logs.
- Use 1–2 bullets per section; link to related files instead of repeating details.
- Prefer short, actionable root cause and fix statements.

## Test Results (Mandatory)

- On SUCCESS, record the result in `work/update.md`.
- On FAIL, write an error log under `test/errorlogs/` and record the resolution in `test/learn-from-log.md` once fixed.
- On SUCCESS after a resolved failure, add a recurrence-prevention rule to `test/learn-from-log.md`.

## Docker-backed Tests (Mandatory)

- If a test requires Docker commands, follow `fivecircles/architecture/specs/docker.md` and the active environment constraints.

## Model Accelerator Preflight (2026-09-07)

- 장기 임베딩/모델 추론 실측 전에 기존 가속 실행 이력, 프로젝트 interpreter, 실제 worker의 명시적 device 및 provider 전달 경로를 확인한다. 작은 CPU smoke의 설정을 검토 없이 계승하지 않는다.
- 실제 허용된 실행 문맥에서 backend 가용성을 확인한다. sandbox 접근 제한과 하드웨어 미지원을 구분하며 필요한 승인 절차를 지킨다. available=true만으로 모델이 GPU에서 실행됐다고 보고하지 않는다.
- 승인된 모델 실행 범위 안에서 최소 대표 입력으로 모델/입력 장치, 실제 연산 성공 및 CPU fallback 여부를 확인한다. GPU 전제인데 CPU로 내려가면 장기 실행 전 원인과 허용된 대체안을 확인한다.
- 선택 device/dtype/batch와 CPU 선택 사유를 실행 설정에 기록한다. 모델 로드·warmup·query·검색/검증 시간을 분리하고 비동기 가속 연산은 완료 동기화를 반영한다.
- 이미 봉인된 실행의 장치·코드·결과를 중간에 수정하지 않는다. 장치 파생 실측은 승인 범위·새 run·환경 receipt로 구분하며 CPU/GPU 지연을 동일 조건으로 합치지 않는다.
- 실모델을 쓰지 않는 Controller/unit test, CPU-only BM25/I/O/무결성 검사는 GPU 사용 의무가 아니다. 이 절은 운영 점검 규칙이며 자동 검증기가 구현됐다는 뜻이 아니다.
- 근거: [CPU 고정·가속 점검 누락 어레스트](errorlogs/backend/2026-09-07-kure-cpu-accelerator-preflight.md).


## Impact-based Validation and Evidence Reuse (2026-09-07)

기존 [승인 실행 규칙](../architecture/todolist.md#실행-규칙--큰-항목을-한꺼번에-구현하지-않는다)의 구체화다. 새 테스트 면제나 실측 실행 승인이 아니며 현재 DIRECTIVE의 필수 검증은 유지한다.

| 변경·판정 대상 | 검증 선택 기준 |
| --- | --- |
| 동작에 영향 없는 문구·설명 | 형식·내용·참조 확인. 계약·권한·검증 규칙을 바꾸는 문서/스킬은 이 행에 포함하지 않는다. |
| 국소 제품 코드 | 영향받는 단위·통합 테스트. 영향 범위가 불명확하거나 공통 의존성을 바꾸면 범위를 넓힌다. |
| 검색·청킹·필터·스키마 | 영향 테스트와 승인 범위 안의 대표 입력 smoke. 실모델·비공개 입력·비용이 필요한 실행은 기존 승인을 별도로 확인한다. |
| 합의된 배치·Phase gate·통합·최종 납품 | 기존 계약에 정한 전체 코드 회귀 및 독립 검수. 모든 내부 leaf마다 전체 검증을 반복하지 않는다. |
| baseline/challenger 검색 성능 판정 | 기존 [평가 계약](../architecture/specs/stage-evaluation-v1.md)과 EXP-SELECT의 승인·동결·분모 기준에 따른 Mini131 비교. 코드 회귀 통과와 별도다. |

- 보안·평가 무결성·데이터 정책·다중 계약 변경의 필수 검수는 [협업 스킬](../agent/skills/collaboration/SKILL.md)이 원천이다. 예상 밖 실패는 먼저 해결하며 다음 의존 작업·통합으로 넘기지 않는다.
- 재사용은 관련 코드·권위 계약·설정·데이터·의존성·환경의 동일성이 입증되고, 필요한 검사가 모두 통과한 증거에 한한다. 대상 ID·명령·종료 상태·산출물 hash와 포함 범위를 기존 폼/receipt에서 참조한다.
- 후보나 환경이 바뀌면 영향을 다시 판정한다. GCP 이관 시 환경 smoke부터 확인하되 환경 의존 증거를 로컬 PASS로 대체하거나 남은 필수 검증을 면제하지 않는다.
- 검증 종류·선택 이유·재사용/재실행 근거는 현재 배치 폼에 기록한다. 이번 정책 정리를 근거로 새 TODO/평가 원장을 만들거나 승인된 131 실행을 취소·축소·중복 실행하지 않는다. 별도 사용자 승인을 받은 장치 이관·부분 실행 보존/중단은 해당 평가 계약과 담당 실행 노트를 따른다.
