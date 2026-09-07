# 협업 메시지 프로토콜

이 문서는 Philosopher와 Coder가 배치 단위로 주고받는 JSON 메시지의 계약이다. 문서 규약일 뿐이며 샌드박스, 권한, 상태 전이 또는 JSON 유효성을 실행 시 강제하는 검증기는 아니다.

## 역할과 경계

- Philosopher는 Astra를 사용한다. `DESIGN` 모드에서는 계약과 방향을 만들고, `FRESH_CRITIC` 모드에서는 새 관점으로 결과를 검토한다. 제품 코드와 테스트 코드를 직접 수정하지 않는다.
- Coder는 Sol Ultra를 사용한다. 지시된 범위에서 구현하고 테스트하며, 실제 결과와 질문을 메시지로 돌려준다.
- 지시는 맹목적으로 따르지 않는다. 요구가 모순되거나 권한·환경·증거 제약상 불가능하면 Coder는 `QUESTION`, `NEEDS_GUIDANCE` 또는 `BLOCKED`로 사실을 보고한다.
- 사용자 요구, 기존 명세, 기존 TODO가 권위 있는 원천이다. 메시지의 변경 요청은 제안이며, 별도의 권위 있는 TASKS JSON을 새로 만들지 않는다.

## 공통 봉투

모든 메시지는 다음 최상위 필드를 가진 JSON 객체다.

| 필드 | 형식 | 의미 |
|---|---|---|
| `schema_version` | 문자열 | 이 계약의 버전 |
| `run_id` | 문자열 | 한 협업 실행의 불투명 식별자 |
| `batch_id` | 문자열 | 배치의 불투명 식별자 |
| `message_id` | 문자열 | 실행 안에서 유일한 불투명 식별자 |
| `in_reply_to` | 문자열 또는 `null` | 답하는 메시지의 `message_id` |
| `sender` | `PHILOSOPHER` 또는 `CODER` | 발신 역할 |
| `kind` | `DIRECTIVE`, `IMPLEMENTATION_REPORT`, `QUESTION`, `REVIEW` | 메시지 종류 |
| `body` | 객체 | 종류별 본문 |

식별자는 결속용 불투명 값이다. 실제 패킷의 파일 목록·내용 해시/커밋·계약 버전·테스트 산출물로 해석 가능해야 한다. 발신자는 존재하지 않는 성공, 해시 또는 테스트 증거를 꾸며내지 않는다. 아래 예시는 설명용이며 실제 실행 증거가 아니다.

## 종류별 최소 본문

### DIRECTIVE

Philosopher가 보낸다. 본문은 다음을 포함한다.

- `mode`: `DESIGN` 또는 `FRESH_CRITIC`
- `contract_id`, `objective`, `scope`, `acceptance_criteria`, `required_tests`, `constraints`, `source_refs`
- `scope`: 최소한 `allowed_files`와 `prohibited_actions`
- `resolution`: 일반 지시는 `null`; `QUESTION` 답변이면 `{question_id, decision, reason}`

질문 답변은 반드시 `kind: "DIRECTIVE"`이고 질문을 `in_reply_to`로 가리키는 완전한 갱신 지시다. `decision`은 `ACCEPT` 또는 `DENY`이며, 승인·거절 이유를 명시한다. 변경점만 보낸 델타는 실행 지시로 보지 않는다.

지시 버전은 DIRECTIVE의 `message_id`로 식별한다. `contract_id`는 승인된 계약 버전이며, 단순 질문 응답 때문에 바꾸지 않는다. 계약을 바꿔야 하면 기존 권위·승인 절차를 먼저 따르고 변경 근거를 패킷에 포함한다.

Relay 시작의 DESIGN 지시는 `direction_assessment`(목표/현재/차이/선정 이유)와
`selected_task_ref`(기존 TODO 참조)를 추가한다. 이는 구현 전 계획이므로 아직 없는
candidate/test evidence나 REVIEW PASS를 요구하지 않는다. 필수 테스트 계획은 포함한다.
`FRESH_CRITIC` 검수 요청은 수락된 Coder 지시를 대체하지 않는다. 결과 REVIEW의
`directive_id`는 실제 구현에 사용한 지시 버전에 결속한다.

### QUESTION

Coder가 보낸다. 토큰을 아끼기 위한 최소 필드는 `contract_id`, `question`, `blocking_constraint`, `evidence`, `options`, `recommendation`, `impact`다. 구현 전후 어느 때든 보낼 수 있고, 해결 전에는 성공으로 간주하지 않는다.

### IMPLEMENTATION_REPORT

Coder가 보낸다. 본문은 다음을 포함한다.

- `status`: `REVIEW_READY`, `NEEDS_GUIDANCE`, `BLOCKED` 중 하나
- `directive_id`, `contract_id`, `candidate_id`, `test_evidence_id`
- `changed_files`: 실제 변경 경로 목록
- `tests`: `{command, exit_code, candidate_id, artifact}` 객체 목록
- `deviations`, `unresolved_questions`, `proposed_next_steps`

`REVIEW_READY`는 후보가 고정되고 필수 테스트 결과가 수집됐다는 뜻일 뿐, 합격을 뜻하지 않는다. 실행하지 않은 테스트에는 성공 코드를 쓰지 않으며 `artifact`는 실제 출력 위치나 `null`이다. `NEEDS_GUIDANCE`와 `BLOCKED`에서도 알려진 후보·증거만 기록하고 모르는 값은 `null`로 둔다.

### REVIEW

Philosopher가 보낸다. `body`는 결정과 무관하게 아래 고정 필드를 모두 가진다.

- `verdict`: `PASS`, `PATCH`, `REPLAN`, `HALT` 중 하나
- `directive_id`, `contract_id`, `candidate_id`, `test_evidence_id`, `reviewed_message_id`
- `direction_score`, `direction_rubric`, `direction_rationale`
- `findings`: `{id, category, severity, evidence, action}` 객체 목록; category는 contract, architecture, implementation, missing_test 중 하나
- `requested_task_changes`: `{proposal, reason, requires_user_authority}` 객체 목록
- `next_batch_constraints`, `reason`, `resume_conditions`

`direction_score`는 `null` 또는 숫자다. 숫자를 쓸 때만 `direction_rubric`에 점수 범위, 평가 항목, 가중치를 명시한다. `null`이면 `direction_rubric`도 `null`이어야 한다. 점수는 판단 근거를 대체하지 않으며 `direction_rationale`은 항상 쓴다.

## 검토 전이 규칙

- 모든 인계의 `run_id`와 `batch_id`도 현재 실행과 일치해야 한다. 같은 이름의
  candidate라도 다른 배치의 지시·로그·review를 현재 기록으로 붙이지 않는다.
  참조가 미상일 때는 확인 대기로 남기며 이전 메시지의 ID를 추측해 채우지 않는다.
- 검토 패킷의 `directive_id`, `contract_id`, `candidate_id`, `test_evidence_id`를 REVIEW에 그대로 결속한다. 다른 후보나 오래된 테스트 증거의 결과를 재사용하지 않는다.
- `PASS`는 같은 후보의 필수 테스트가 통과하고 기존 정책상 허용된 제외 외 미실행·실패가 없으며, `unresolved_questions`와 차단 이슈가 없을 때만 가능하다. 테스트를 단순히 종료한 것은 통과가 아니다.
- 응답이 없거나, 오래됐거나, JSON이 잘못됐거나, 결속 식별자가 다르면 디스패처 상태는 `WAITING_REVIEW`다. 이를 `PASS`로 대체하지 않는다.
- 식별자가 맞아도 필수 실패 증거와 모순되는 PASS는 무효다. `WAITING_REVIEW`로 유지하고 정정 검수를 요청한 뒤 PATCH/REPLAN 지시로 연결하며 last-pass를 갱신하지 않는다.
- `PATCH` 뒤에는 Coder가 수정한 새 후보 스냅샷과 새 테스트 증거를 보고하고, Philosopher가 다시 검토한다.
- 기본 재시도 한도는 같은 finding이 두 번 반복될 때까지다. 두 번째 반복 뒤에는 `REPLAN`하며 자동 합격시키지 않는다.
- `REPLAN`은 사용자에게 이미 허용된 범위 안에서만 계획을 바꾼다. 새 권한, 요구 변경 또는 범위 확대가 필요하면 차단 상태로 남기고 사용자 결정을 기다린다.
- `HALT`는 `reason`과 비어 있지 않은 `resume_conditions`를 요구한다. 사용자가 조건을 충족시키거나 명시적으로 재개할 수 있다.

## 상태와 보존

- `state.json`의 유일한 소유자는 메인 디스패처다. 작업자와 리뷰어는 상태 파일을 직접 수정하지 않는다.
- 최소 상태: run_id, batch_id, phase, 역할별 실제 agent_id/model/effort, active_directive_id, 현재 candidate/contract/test_evidence 식별자, waiting_for, last_pass_candidate_id와 다음 재개 지점. phase는 DESIGN, WORK, WAITING_GUIDANCE, WAITING_REVIEW, REPAIR, READY_TO_INTEGRATE, CLOSED, BLOCKED 중 하나다.
- 이벤트 메시지는 배치별 JSON 파일로 보존하며, 예를 들어 `messages/<batch_id>/<sequence>-<message_id>.json`처럼 이름을 정한다. 저장된 이벤트는 불변이다.
- 메인 디스패처는 응답을 읽어 JSON과 결속 식별자를 확인한 뒤에만 파일과 상태에 반영한다. 리뷰어는 JSON을 반환할 뿐 파일을 쓰지 않는다.
- `last_pass_candidate_id`는 유효한 `PASS`와 필수 검증 완료 뒤에만 해당 후보로 이동한다.
- 메시지 저장소는 기존 요구사항, 명세 또는 TODO를 복제해 새 권위 원천으로 만들지 않는다.

Relay 사용 시 같은 상태에 `lifecycle_substage`, `closeout_ref`,
`integration_receipt_ref`, `report_fingerprint`, `continuation`을 필요에 따라
추가한다. 의미와 재진입 규칙은 [Relay 라이프사이클](relay-cycle.md)에만 정의한다.
새 phase 집합이나 별도 TASKS 원장을 만들지 않는다.

## 유효한 DIRECTIVE 예시

```json
{
  "schema_version": "1.0",
  "run_id": "run-example",
  "batch_id": "batch-parser",
  "message_id": "msg-directive-1",
  "in_reply_to": null,
  "sender": "PHILOSOPHER",
  "kind": "DIRECTIVE",
  "body": {
    "mode": "DESIGN",
    "contract_id": "contract-parser-1",
    "objective": "고정 입력으로 파서의 필드 매핑을 검증한다.",
    "scope": {
      "allowed_files": ["src/parser.ts", "tests/parser.test.ts"],
      "prohibited_actions": ["요구사항 수정", "고정 golden 수정"]
    },
    "acceptance_criteria": ["필수 필드가 손실 없이 매핑된다."],
    "required_tests": ["npm test -- tests/parser.test.ts"],
    "constraints": ["저장소에 고정된 fixture만 사용한다."],
    "source_refs": ["specs/parser.md"],
    "resolution": null
  }
}
```

## 고정 fixture 질의 왕복

1. Coder가 지시에 적힌 `fixtures/pinned-v3.json`이 없음을 확인하고 `QUESTION`을 보낸다: `{"contract_id":"contract-parser-1","question":"고정 fixture 경로를 어느 파일로 확정할까요?","blocking_constraint":"pinned-v3가 없음","evidence":["fixtures에는 pinned-v2.json만 있음"],"options":["기존 pinned-v2 사용","사용자에게 fixture 요청"],"recommendation":"기존 pinned-v2 사용","impact":"경로 확정 전 필수 테스트 불가"}`.
2. 계약에서 호환 단위 테스트 fixture 선택을 허용하는 경우에만 Philosopher가 pinned-v2 사용을 수락한다. 새 전체 DIRECTIVE는 `message_id: "msg-directive-2"`, 같은 `contract_id: "contract-parser-1"`을 사용하고 QUESTION을 `in_reply_to`로 가리킨다. `resolution`은 `{"question_id":"msg-question-1","decision":"ACCEPT","reason":"승인 계약이 허용한 호환 단위 테스트 입력임을 확인함"}`이다. 특정 v3 또는 frozen golden이 필수이면 대체하지 않고 DENY와 이유·입력 확보 조건을 반환한다.
3. Coder는 제품 코드와 테스트만 바꾸고 frozen golden과 요구사항은 그대로 둔다. `REVIEW_READY` 보고에 `directive_id: "msg-directive-2"`, 실제 후보·증거 ID, 변경 경로, 테스트의 명령·종료 코드·동일 후보 ID·출력 위치, 빈 `unresolved_questions`를 기록한다.
4. Philosopher는 그 보고와 정확히 같은 후보·계약·테스트 증거를 검토해 아래 REVIEW를 반환한다. 식별자나 필수 테스트가 맞지 않으면 이 예시처럼 합격시키지 않고 `WAITING_REVIEW` 또는 적절한 비합격 결정을 사용한다.

## 유효한 REVIEW 예시

```json
{
  "schema_version": "1.0",
  "run_id": "run-example",
  "batch_id": "batch-parser",
  "message_id": "msg-review-1",
  "in_reply_to": "msg-report-1",
  "sender": "PHILOSOPHER",
  "kind": "REVIEW",
  "body": {
    "verdict": "PASS",
    "directive_id": "msg-directive-2",
    "contract_id": "contract-parser-1",
    "candidate_id": "candidate-parser-2",
    "test_evidence_id": "evidence-parser-2",
    "reviewed_message_id": "msg-report-1",
    "direction_score": null,
    "direction_rubric": null,
    "direction_rationale": "허용 범위 안에서 요구된 매핑과 검증이 완료됐다.",
    "findings": [],
    "requested_task_changes": [],
    "next_batch_constraints": ["frozen golden과 요구사항을 계속 변경하지 않는다."],
    "reason": "같은 후보의 필수 테스트가 완료됐고 미해결 차단 이슈가 없다.",
    "resume_conditions": []
  }
}
```
