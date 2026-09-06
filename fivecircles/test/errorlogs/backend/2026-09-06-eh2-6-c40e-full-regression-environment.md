# EH2.6.c4.0.e 전체 회귀 환경 의존성 기록

- 기록: 2026-09-06 KST
- 범위: `EH2.6.c4.0.e` structural-effect bridge 구현 후 전체 Python 회귀
- 명령: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -p 'test*.py'`

## 결과

- 총 1,438건 실행. 23 errors와 2 failures가 발생했으며 신규 bridge focused/인접 테스트 실패는 0건이다.
- 오류는 private index lock 권한, 실행한 Python의 `tiktoken`·`pypdf`·`kiwipiepy` 미설치, transformers API 버전 불일치,
  sandbox loopback 정책으로 재현됐다.
- `tests.test_controller_structural_effect_bridge` 7/7, c4.0.c/d/e 인접 50/50은 별도 PASS했다.
- `git diff --check`와 repository safety 940파일은 PASS했다.

## 판정과 대응

- 코드 회귀 실패로 분류하지 않고 환경 의존성 blocker로 보존한다. 최초 전체 결과를 소급해 PASS로 바꾸지 않는다.
- 영향을 받은 private-index 테스트는 권한 경계에서 재실행하고, 선택 의존성 설치 또는 공식 실행환경 확보 후
  전체 회귀를 다시 수행한다.
- 이번 leaf는 synthetic/offline fixture만 사용했으며 API/OpenAI/model/Langfuse/golden/VLM/provider/clock 호출은 0회다.

## 실행환경 정정 및 수리 (2026-09-06 11:49 KST)

- 최초 명령의 bare `python`은 Miniconda Python 3.13을 선택했다. 프로젝트 `.venv`는 Python 3.12.14이며,
  필요한 패키지가 이미 설치되어 있었다. 프로젝트 전체의 패키지 미설치로 설명한 것은 잘못된 진단이다.
- Miniconda의 transformers 5.14.1은 프로젝트 `<5` 조건 밖이다. `.venv`의 4.57.6은 lock과 일치한다.
  앞서 기록한 "구형 transformers"는 정정한다. 나머지 두 권한 오류는 당시 도구 sandbox에서 발생했다.
- `.venv`에서 extras 전체 설치 명령을 재실행해 의존성을 동기화했다. 기존 패키지는 모두 조건을 충족해
  신규 다운로드/버전 변경 없이 프로젝트 editable 설치만 갱신했다. `pip check`: No broken requirements found.
- 확인 버전: pypdf 6.16.2, tiktoken 0.13.0, kiwipiepy 0.23.2, kiwipiepy_model 0.23.0,
  transformers 4.57.6. base `pip install -e .`만 안내하던 README를 전체 extras 및 `.venv` 명령으로 수정했다.
- 기존 실패가 속한 10개 테스트 모듈 재검증: **153/153 PASS, 111.262초, exit 0**. `.index.lock` 및
  실제 macOS sandbox 검사도 포함한다. 원본 23 errors/2 failures 기록은 유지하며 이번 결과로 소급하지 않는다.

설치 명령:

```bash
.venv/bin/python -m pip install --quiet --no-build-isolation -e '.[test,rag,evidence-harness,gcp-local,pdf-fidelity,hwp,ui,observability]' -c requirements/gcp-local-lock.txt
.venv/bin/python -m pip check
```

집중 검증 로그: `/private/tmp/midprojectrag-env-repair-focused-20260906.log` (로컬 임시 파일).
전체 검증은 `.venv/bin/python`과 `discover -s tests -t . -p 'test*.py' -v`로 별도 실행한다.

## 해결 확인 (2026-09-06 11:53 KST)

- **전체 1,498/1,498 PASS; errors 0, failures 0, skipped 0; 211.055초; exit 0.**
- 기존 오류 25건을 포함한 회귀가 정상 통과했다. 이전 import 실패로 수집되지 못했던 모듈이 복구되어
  총수가 1,438 → 1,498로 늘었다. 이번 수리에서는 애플리케이션 코드·테스트·ML lock을 변경하지 않았다.
- ML lock에 명시된 32개 패키지의 설치 버전을 모두 비교해 불일치 0건을 확인했다.
- README 및 testpolicy에 전체 extras, `.venv/bin/python`, fixture import를 위한 `-t .` 명령을 고정했다.
- UI/브라우저 수동 조작·실제 모델 성능 실험은 이번 환경 수리의 범위가 아니다. 전체 suite의 Streamlit AppTest는 포함했다.

전체 재검증 명령:

```bash
PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python -m unittest discover -s tests -t . -p 'test*.py' -v
```

원시 실행 로그: `/private/tmp/midprojectrag-env-repair-full-20260906.log` (로컬 임시 파일).
최종 판정: **PASS / 환경 오류 해결**. 최초 실패 실행은 역사적 기록으로 보존한다.
