# Evidence-Harness progress report Playwright runtime discovery

- 날짜: 2026-09-05
- 범위: c2 flow HTML desktop/mobile 검증
- 상태: RESOLVED

## 증상

첫 실행은 global Node의 `NODE_PATH`에 Playwright가 없어 `Cannot find module 'playwright'`로 끝났다. Codex
bundled Node/package 경로로 바꾼 두 번째 실행은 기본 Chromium revision이 로컬에 없어 launch 전에 끝났다.

## 원인

보고서 검증 명령이 현재 desktop task가 제공하는 workspace dependency 경로와 설치된 브라우저를 아직
해석하지 않았다. HTML이나 다이어그램 자체의 실패는 아니었다.

## 수리

workspace dependency tool이 반환한 bundled Node와 package path를 사용하고, 다운로드 없이 이미 설치된
Google Chrome executable을 명시해 같은 검증을 다시 실행했다.

## 검증

최종 Playwright 결과: images 2, tables 8, page errors 0, mobile overflow false. 스크린샷은
`fivecircles/test/playwright-screenshots/evidence-harness-progress-eh26-c2-2026-09-05.png`에 저장했다.

## 예방

다음 정적 보고서 QA도 먼저 workspace dependency를 조회하고, bundled package path와 설치된 브라우저를
명시한다. package/browser 부재를 product regression으로 보고하지 않는다.
