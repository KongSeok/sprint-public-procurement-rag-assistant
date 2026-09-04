# c1 flow report validation tooling

- 브라우저: local `file://` navigation이 URL security policy에서 page load 전에 차단됐다. 우회하지 않았다.
- `xmllint`/`tidy`: 설치본이 HTML5 `main`, `section`, `figure`를 인식하지 못해 validator로 사용할 수 없었다.
- Python: 선택 parser `html5lib`가 환경에 설치되지 않아 import가 실패했다. 설치·network 요청은 하지 않았다.
- 대체 증거: Mermaid PNG 생성 성공·직접 이미지 검사, HTML 로컬 자산 존재/참조와 c1/c2 상태 문자열 확인.
- 판정: PNG/static PASS, HTML browser visual QA는 environment-blocked. visual PASS로 승격하지 않는다.
- 기존 규칙: `2026-08-30-flow-report-file-url-policy.md`의 비우회 방침을 재사용한다.
