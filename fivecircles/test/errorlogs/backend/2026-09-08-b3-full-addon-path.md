# B3 전체 검사 — 기존 HB add-on 경로 누락

- 시각: 2026-09-08 19:06 KST. 배치 EH2.6.c4.2.b.3, 후보49ff508f….
- 실제 결과: source-only 전체 discovery에서 tests.test_hb_mini131 import가 langchain_text_splitters 누락으로 실패했다. 4.973초/exit1, 실행 테스트0. 수집1759에는 실패 placeholder가 포함되어 성공 분모가 아니다.
- 원인: HB가 별도 설치한 /private/tmp/hb-qwen-local-addons-20260908-001/site-packages를 이번 full 프로세스 PYTHONPATH에 넣지 않았다. 프로젝트 .venv 자체의 pip check는 정상이어도 별도 테스트 의존성을 보장하지 않는다.
- 확인: 기존 경로의 langchain-core1.6.2, langchain-text-splitters0.3.11, rank-bm250.2.2 버전·실제 import origin·각 배포1개를 확인했다. src/midprojectrag/hb_mini131.py의 핀 및 HB 작업 원장과 일치한다.
- 복구 범위: Design이 v5에서 full-only 기존 add-on 읽기 전용 재사용과 새 full1회를 수락했다. .venv/제품/HB/원본/기대값 변경·새 설치·테스트 제외·import 대체는 없다. source-only 격리/집중/인접 환경은 유지한다.
- 상태: 환경 사전 import PASS, 새 전체 검사 완료 전이다. 기존 실패는 /private/tmp/b3-resume-20260908.uNltdg/first-parent-resume-full-result.json과 native log에 보존한다. 새 full에서 add-on 파일·배포·origin·기존 환경 전후를 별도로 대조한다.
- 재발 방지: 전체 discovery 전, 병렬 작업의 테스트 전용 추가 경로도 확인한다. 환경이 다른 증거를 동일 조건 PASS로 합치지 않는다.
