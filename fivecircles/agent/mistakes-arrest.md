# MidProjectRAG Operational Mistake Guards

This active file contains only project-independent recurrence guards.

## Guards

- Resolve paths from `/Users/pio/Documents/AIENGINEERCOURSE/MidProjectRAG`; do not modify the similarly named ChatGPT workspace copy.
- Never use reset/checkout commands to discard files outside the active task scope.
- Do not infer a model API call is authorized merely because a provider is named in the assignment.
- Keep private corpus and derived artifacts outside Git and run the repository safety check before integration.
- When an error is new, diagnose it from current code and tests before promoting a reusable rule here.
- Before diagnosing missing Python dependencies, inspect the repository interpreter with `.venv/bin/python -c 'import sys; print(sys.executable, sys.version)'` and `.venv/bin/python -m pip check`. Do not assume bare `python` selects the project environment.
- Install and test with the same explicit interpreter. Follow `../test/testpolicy.md` for full-suite extras and `unittest discover -s tests -t .`; check installed versions against the existing lock before changing them.
- Do not close an actionable failure as merely an environment blocker: apply the known runtime/permission correction and rerun affected tests. Keep the original failure and corrected run distinct, including collection counts and skips.

## Arrest Record — 2026-09-06 Python 실행환경 오선택

- **실수:** 기존 venv 사용 규칙을 적용하지 않고 Miniconda Python 3.13으로 전체 회귀를 실행했다.
  프로젝트 `.venv`에 이미 있는 패키지를 미설치로 설명하고, 설치된 transformers 5.x를 "구형"으로 잘못 분류했다.
- **영향:** 최초 1,438건에서 오류23·실패2·skip5가 발생했다. Python 선택 오류에 당시 sandbox 권한 문제가 겹쳤다.
  원인을 설명하는 과정에서도 같은 환경으로 전체 테스트를 반복해 시간과 실행 비용을 낭비했다.
- **교정:** `.venv` Python 3.12.14로 전환, extras 동기화·pip check·ML lock32 일치를 확인했다.
  기존 실패 영역153/153 및 전체1498/1498 PASS(오류/실패/skip0). 앱 코드·테스트 변경 없이 해결했다.
- **재발 방지:** 위 interpreter 사전 확인 → 프로젝트 runtime/lock 정합 확인 → 실패 영역 재검증 → 필요한 전체 회귀 순서를 적용한다.
  문서 기록만으로 오류를 종료하지 않으며, 라이브러리 미설치/버전 불일치 진단은 실행한 환경을 명시한다.
- **근거:** [상세 오류·해결 기록](../test/errorlogs/backend/2026-09-06-eh2-6-c40e-full-regression-environment.md),
  [테스트 실행 정책](../test/testpolicy.md), [기존 venv 사용 교훈](../test/learn-from-log.md#harness-tests-must-use-the-repository-runtime-2026-09-05).
