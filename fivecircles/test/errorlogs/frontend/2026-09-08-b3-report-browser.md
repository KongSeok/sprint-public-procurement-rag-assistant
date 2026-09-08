# B3 보고서 브라우저 실행 파일 누락

- Context: 같은 배치의 최종 HTML/PNG 오프라인 표시 검사.
- Issue: bundled Playwright가 지정한 chromium-1234 실행 파일 부재로 launch 실패, exit1. 페이지 검사는 실행되지 않았다.
- Resolution: 검사 스크립트의 기존 MIDPROJECTRAG_REPORT_CHROMIUM 설정에 설치된 Chrome152.0.7977.82를 지정. 패키지·스크립트·사용자 프로필 변경이나 새 설치 없음.
- Result: 동일 스크립트 재실행 exit0. desktop1440x1000/mobile390x844, 도형2·표8, 페이지 오류/외부 요청0, 모바일 가로 넘침0.
- Evidence: native chunks b62e9b(실패), 6612fa(성공), 스크립트 scripts/check_harness_progress_report.cjs; 화면 ../../playwright-screenshots/controller-first-parent-2026-09-08.png.
- Prevention: 보고서 검사 전 자동화 라이브러리 경로와 실제 브라우저 실행 파일을 구분해 확인한다. 설치 없이 기존 지원 설정으로 경로를 명시할 수 있다.
