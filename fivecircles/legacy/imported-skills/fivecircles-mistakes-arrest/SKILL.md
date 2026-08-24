<skill name="mistakes-arrest">
  <description>Prevents recurring mistakes by checking against a known list of incidents. Use when the user says "arrest this mistake", "mistake arrest", or when a similar error pattern is detected.</description>
  <instructions>
# Mistakes Arrest

Purpose
- 경로 실수(컨트롤러/스펙/게이트웨이 불일치) 재발 방지.

Trigger
- 404/경로 불일치 발생
- v1/v2 prefix 혼선
- "api-contract랑 경로 안맞음" 피드백

Alignment Flow (Keyword Check)
1) 키워드 스캔
- controllers: `@RequestMapping`, `@GetMapping`, `@PostMapping`
- docs: `Base URL`, `GET /`, `POST /`
- gateway: `/api/*` routes

2) 기준 문서 확인
- `fivecircles/architecture/specs/api-contract.md`
- `fivecircles/architecture/specs/event-v2-api.md`
- `services/api-gateway/src/main/resources/application-docker.yml`

3) 불일치 분류
- [경로설정] base URL 불일치
- [api분류] v1/v2 prefix 혼선
- [게이트웨이] 라우트 누락/리라이트 문제

4) 수정 순서
- 컨트롤러 경로 → 스펙 문서 → 게이트웨이 라우트
- 내 영역 외 파일은 `origin/develop`로 되돌림

5) 테스트
- 서버 curl로 v1/v2 대표 엔드포인트 확인

6) 기록
- `fivecircles/work/update.md`
- 필요 시 `fivecircles/scoring/optimization.md`

Response Output Arrest
- Trigger: "diff 보여줘", "출력 보여줘" 요청인데 요약만 전달한 경우.
- Rule: 요청받은 출력(디프/로그)을 먼저 제공하고, 요약은 확인 요청 후 제공.

Commit Timing Guardrail
1) 커밋 전 체크
- "새 브랜치 + 투두 완료 후 커밋" 지시 여부 확인
- 지시가 있으면 커밋 금지
2) 실수 시 조치
- 즉시 스테이징/커밋 중단
- `fivecircles/agent/mistakes-repeating.md`에 기록

Server Sync Guardrail
1) 테스트 전 체크
- `fivecircles/architecture/specs/test-server-policy-4C.md`의 Latest Sync Check 실행
2) 불일치 시 조치
- 서버에서 develop 최신화 후 테스트 재개

Tool Usage Compliance
- Trigger: User explicitly instructs to use a specific tool (e.g., "Use Playwright").
- Mistake: Attempting alternative methods (e.g., `browse_web`, `curl`) that fail or are inappropriate.
- Arrest: MUST use the requested tool. If the tool is unavailable to the current agent, delegate the task to an agent (e.g., Codex) that can use it.
- Reference: User instruction "playwright 써서 프론트 점검하라니까?".

Tool Recognition Failure
- Trigger: Claiming "I don't have the tool" when it is actually available (e.g., `fetch_page` from Playwright MCP).
- Mistake: Falsely delegating tasks or refusing work due to incomplete check of available tools.
- Arrest: ALWAYS check `.mcp.json` definitions and the current `available_tools` list before claiming inability. Recognize aliases (e.g., `fetch_page` IS Playwright).
- Reference: User instruction "뭐야 없다고? 분명 만들었는데?".

## Incident (2026-01-22) - Gemini 필독
- Mistake (원인): auth-service는 `UserValidationResponse.userId`를 기대하지만 user-service는 `UserAuthResponse.id`로 응답해 JWT에 userId 클레임이 비어짐.
- Symptom: 로그인 직후 `/api/user/v1/me`가 500, user-service 로그에 `MissingRequestHeaderException: X-User-Id`.
- Detection: 로그인 200 OK + user DB 존재 확인 + /me 500 조합으로 매핑 누락을 역추적.
- Arrest (해결법): DTO 필드명 정렬(`id` → `userId` 또는 `@JsonProperty("id")`) 후 login → /me 헤더 주입 여부까지 재검증.

## Incident (2026-01-23) - Gemini 필독
- Mistake (원인): `replace` 툴 사용 시 기존 내용(announcements)을 충분히 포함하지 않은 `new_string`을 구성하여, 의도치 않게 기존 텍스트(alias 관련 공지 등)가 삭제될 뻔한 위험 초래.
- Symptom: 유저가 "왜 갑자기 앨리어스 명령어를 치려 하느냐"며 의도와 다른 동작(또는 데이터 손실 위험)을 감지하고 지적함.
- Detection: `replace` 툴의 `old_string`과 `new_string` 파라미터 구성 시, 파일의 전체 문맥(context)을 무시하고 부분적으로만 덮어쓰려다 발생.
- Arrest (해결법): 리스트나 블록 구조의 파일을 수정할 때는 **기존 내용을 반드시 포함**하여 `new_string`을 작성하거나, 수정 범위를 최소화하여 다른 정보가 유실되지 않도록 엄격히 검증할 것. 수정 전 `read_file`로 확인한 내용과 수정 후의 예상 결과가 일치하는지 한 번 더 생각할 것.

## Incident (2026-01-26) - Duplicate Import
- Mistake (원인): 타입스크립트 파일(`EventTimelinePage.tsx`) 수정 시, 이미 상단에 존재하는 import 구문을 확인하지 않고 중복으로 타입을 import 함.
- Symptom: `Identifier 'Drama' has already been declared` 빌드 에러 발생.
- Arrest (해결법): 코드 추가 시 파일 상단의 `import` 섹션을 먼저 확인(read_file)하거나, IDE/Linter가 없는 환경에서는 문자열 검색(grep)을 통해 해당 심볼이 이미 import 되어 있는지 확인할 것.

## Incident (2026-01-26) - Missing Playwright Dependency
- Mistake (원인): Playwright 테스트 실행 요청을 받았으나 `front/package.json`에 `@playwright/test`가 누락되어 있어 실행 실패.
- Symptom: `npm list` 실패, 테스트 실행 불가.
- Arrest (해결법): Playwright 관련 작업을 수행하기 전에 반드시 `package.json`을 확인하고, 필요한 경우 `npm install --save-dev @playwright/test` 및 브라우저 설치(`npx playwright install chromium`)를 선행할 것.

## Incident (2026-01-26) - Docker Port Mismatch
- Mistake (원인): `api-gateway`는 환경변수로 포트(8084)를 받아 라우팅하지만, 대상 서비스(`character-service`)는 `docker-compose.yml`에서 해당 포트 변수를 주입받지 못해 기본 포트(8080)로 구동됨.
- Symptom: Gateway에서 500 Error (`Connection Refused`) 발생.
- Arrest (해결법): `docker-compose.yml` 작성 시, `.env`에 정의된 포트 변수를 `api-gateway`뿐만 아니라 **대상 서비스의 `SERVER_PORT` 환경변수**로도 반드시 주입하여 포트를 동기화할 것.

## Incident (2026-01-26) - Mock Data Masking 500 Error
- Mistake (원인): 프론트엔드가 초기 로딩 시 Mock 데이터나 정적 데이터를 보여주어, 실제 백엔드 API가 500 에러를 내고 있음에도 "정상 작동"으로 오판함.
- Symptom: 메인 페이지는 뜨지만, 상세 페이지 이동이나 버튼 클릭 시 500 에러 또는 타임아웃 발생.
- Arrest (해결법): "접속 확인"에 그치지 말고, **실제 API 호출이 발생하는 상호작용(버튼 클릭, 상세 진입)**까지 자동화 테스트(Playwright)에 포함시켜야 함. "화면이 보인다"는 것과 "서비스가 된다"는 것은 다름을 인지할 것.

## Incident (2026-01-26) - Ignored File Read Failure
- Mistake (원인): 로그 파일이나 임시 파일(`errorlogs/`) 등 `.gitignore`에 포함된 파일을 `read_file` 툴로 읽으려다 실패함.
- Symptom: `File path ... is ignored by configured ignore patterns` 에러 발생.
- Arrest (해결법): 로그, 빌드 아티팩트 등 gitignore 대상 파일을 읽어야 할 때는 `read_file` 대신 **`run_shell_command("cat <file>")`**를 사용하여 파일 시스템에 직접 접근할 것.

## Incident (2026-02-01) - Assumption-Based Coding
- Mistake (원인): `event` 테이블에 관례적으로 `created_at` 컬럼이 있을 것이라 가정하고, 실제 스키마(`V*.sql`)나 엔티티(`Event.java`) 확인 없이 스크립트를 작성하여 실행함.
- Symptom: `Unknown column 'created_at' in 'field list'` 에러 발생으로 작업 중단.
- Arrest (해결법): DB 조작 스크립트 작성 전에는 반드시 **Schema 파일(`src/main/resources/db/migration/*.sql`) 또는 Java Entity**를 `read_file`로 확인하고, 팩트에 기반하여 코드를 작성할 것. 추측 금지.

## Incident (2026-02-01) - Incorrect Env Reference
- Mistake (원인): 로컬 실행을 위한 환경 설정을 찾을 때, 실제 설정 파일(`.env`)이 숨겨져 있거나 보안상 꺼린다는 이유로 템플릿 파일(`.env.example`)을 참조하여 설정값을 추론함.
- Symptom: 실제 `.env`와 템플릿의 포트/계정 정보가 달라 DB 접속 실패 또는 엉뚱한 포트로 연결 시도.
- Arrest (해결법): 로컬 실행 시 **Source of Truth는 무조건 `.env` 파일**임. `ls -a`로 존재를 확인하고, `run_shell_command("cat .env")` 등으로 내용을 직접 확인하여 정확한 접속 정보를 사용할 것. (보안 주의: 출력된 비밀번호는 로그에 남기지 않거나 마스킹 처리).

## Incident (2026-02-01) - Skill Activation Failure
- Mistake (원인): 사용자가 "어레스트해", "운영방침 초기화" 등 특정 스킬 발동을 암시하는 키워드를 사용했음에도, `activate_skill` 도구를 호출하지 않고 텍스트로만 "하겠습니다"라고 응답함.
- Symptom: 스킬의 전문 지침(Instructions)을 로드하지 않은 채 일반적인 방식으로 업무를 처리하여, 스킬이 보장하는 품질/절차를 준수하지 못함.
- Arrest (해결법): 사용자의 명령에 스킬 키워드가 포함되거나 해당 스킬의 기능이 필요하다고 판단되면, 주저 없이 **`activate_skill`** 도구를 최우선으로 호출하여 전문 모드로 전환할 것. 말보다 행동(Tool Call)이 먼저다.
  </instructions>
</skill>