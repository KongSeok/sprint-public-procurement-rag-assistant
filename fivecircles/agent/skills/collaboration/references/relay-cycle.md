# Relay 협업 라이프사이클

이 레퍼런스는 relay-shot 계열이 collaboration 모드로 실행될 때의 배치 연결 규칙이다.
역할·모델·메시지·검수·상태의 원천은 [협업 스킬](../SKILL.md)과
[메시지 계약](messages.md)이다. 이 문서는 해당 계약을 재정의하지 않는다.
기존 solo 모드도 유지한다. 협업 모드 선택은 커밋·push·범위 확대 승인이 아니다.
상위 사용자 권한과 보안·데이터 규칙이 모든 단계에 우선한다.

## 단일 조정자와 기록

- 메인 조정자 한 명만 전체 반복 루프와 기존 협업 상태를 소유한다.
- Design은 Astra, Coder는 Sol Ultra, Critic은 매 검수마다 별도 fresh Astra다.
  실제 호출 방식과 모델 확인·실패 처리는 기존 협업 계약을 따른다.
- 제품 코드·테스트 구현은 Coder만 한다. 메인은 판정 확인·기록·통합을 조정한다.
- 하위 역할은 현재 배치의 지시·질문·결과만 반환한다. child relay를 시작하지 않는다.
- 기존 flowform에 scope, acceptance, review, log, integration, next의 실제 참조를 붙인다.
  참조는 승인 요구/명세/TODO, 메시지 ID, 증거 파일, 실제 영수증 위치를 가리킨다.
- 새 요구사항 원장이나 TODO 원장을 만들지 않는다. 기존 상태 파일이 있으면 재사용한다.
- `phase` 값과 메시지 종류는 기존 계약 그대로 쓴다. 필요하면 상태의 부가필드
  `lifecycle_substage`에 `start_report`, `closeout`, `integration`, `reentry` 등을 기록한다.
  부가필드는 두 번째 phase나 독립 전이 원장이 아니며 메인만 갱신한다.
- 이 규칙은 문서 프로토콜이다. runtime enforcer, 상주 scheduler, 모델 전환기,
  read-only sandbox를 설치하거나 그러한 강제가 있다고 주장하지 않는다.

관련 스킬은 필요한 단계에서 읽는다: `relay-shot`은 작업 선정·계속 여부,
`doc-contract-writer`는 Design 계약, `one-go`/`batch-sequential-runner`는 Coder 실행,
`test-runner`는 테스트 증거, `peer-review`는 Critic 검수 기준(기록은 메인),
`mermaid-flow-report`는 비교 보고, `logall`은 배치 기록이다.
`one-shot-delivery-orchestrator`와 그 protocol은 이 단일 루프의 배치 절차이지
별도 경쟁 루프가 아니다. 프로젝트 설치본을 우선하고 없으면 사용 가능한 전역 스킬을 찾는다.
명시된 프로젝트가 아닌 AlphaFlower 등의 예시 경로를 현재 프로젝트 계약으로 채택하지 않는다.

## 1. DESIGN: 목표와 현재 상태에서 시작

1. 실제 작업 트리·브랜치·승인 범위·기존 영수증을 확인한다. 타인 변경을 구분한다.
2. Astra Design이 승인 목표와 현재 구현·테스트·남은 TODO를 비교한다.
3. 목표에 필요한 다음 배치를 승인 범위 안에서 고르고 완료 조건을 구체화한다.
4. 기존 DIRECTIVE 최소 본문 전체를 채운다. 목표, in/out, 허용 파일, 금지 작업,
   계약 참조, acceptance, 필수 테스트, 제약·중단 조건과 source_refs를 포함한다.
5. 아직 구현되지 않은 후보에 REVIEW PASS를 요구하지 않는다. 시작은 설계 판단이다.
6. 메인이 실제 Coder에게 완전한 DIRECTIVE를 전송한 후 `WORK`로 진행한다.
   다음 지시를 작성하거나 TODO를 골랐다는 이유만으로 다음 배치를 started로 표시하지 않는다.

시작 보고는 목표 대비 현재 상태와 선택 이유를 담는다. 마지막 종료 보고의 대상
fingerprint가 같으면 그 보고를 참조해 재사용할 수 있다. fingerprint는 제품 코드,
권위 계약, 평가 설정/데이터 식별자, 관련 실행 환경의 식별 가능한 스냅샷을 포함한다.
동일성을 입증하지 못하거나 한 요소라도 달라지면 영향 부분을 다시 확인한다.
보고 재사용은 필수 테스트나 결과 후보의 fresh Critic 검수를 면제하지 않는다.
fingerprint 변경 자체가 아직 구현하지 않은 다음 배치의 사전 PASS를 요구하지는 않는다.
기존 완료 후보의 유효성/의존 조건이 깨졌으면 그 부분을 재검증하고, 그렇지 않으면
갱신된 Design 지시로 Coder를 시작한다. 새 배치의 결과 검수는 구현·테스트 이후다.

## 2. WORK: 현재 배치 구현과 질문

- Coder는 수락한 DIRECTIVE 버전의 현재 배치만 구현하고 요구 테스트를 실행한다.
- 불명확한 계약·환경·권한·반복 실패는 QUESTION으로 근거와 영향을 보고한다.
  메인은 `WAITING_GUIDANCE`를 사용하고 막힌 의존 작업을 진행시키지 않는다.
- Design의 답은 기존 메시지 계약에 맞는 완전한 갱신 DIRECTIVE다.
  질문 해결을 핑계로 계약이나 사용자 범위를 조용히 넓히지 않는다.
- Coder는 실제 후보·계약·테스트 증거를 결속한 IMPLEMENTATION_REPORT를 반환한다.
  REVIEW_READY는 검수 준비 상태이며 완료 승인이나 통합 권한이 아니다.

## 3. WAITING_REVIEW: 결과 후보를 fresh Critic에게 전달

1. 메인이 후보를 고정하고 실제 diff·관련 전체 파일·필수 증거의 참조를 모은다.
   staged/unstaged/untracked와 제외된 타인 변경도 식별한다.
2. 별도 fresh Astra Critic에게 DIRECTIVE, contract, exact candidate,
   test_evidence와 원래 IMPLEMENTATION_REPORT를 전달한다.
3. Critic은 기존 REVIEW 전체 필드를 반환한다. 메인은 directive/contract/candidate/
   test_evidence/reviewed_message 결속과 필수 실패·미해결 질문 여부를 확인한다.
4. 응답 누락·잘못된 형식·대상 불일치는 기존 규칙대로 WAITING_REVIEW다.
5. PATCH는 `REPAIR`에서 같은 Coder가 수정하고 새 후보·증거로 fresh 재검수한다.
   REPLAN은 `DESIGN`으로, HALT는 사유와 재개 조건을 가진 `BLOCKED`로 연결한다.
   같은 지적의 반복 실패 처리와 재시도 기준도 기존 메시지 계약을 따른다.
6. 유효한 PASS와 필수 검증 완료 후에만 last-pass 포인터를 갱신한다.

배치 종료 Critic의 `next_batch_constraints`를 다음 Design 입력으로 전달한다.
동일 대상·동일 목적의 Astra 검수를 종료와 다음 시작에서 두 번 반복하지 않는다.
다음 Design은 제약을 적용해 작업을 선택하며, 다음 결과 후보는 다시 fresh 검수를 받는다.

## 4. READY_TO_INTEGRATE: 한 번의 closeout과 허용된 통합

1. 유효한 PASS, 같은 대상의 필수 테스트, 로그·커밋·push 각각의 권한을 확인한다.
   후속 필수 검증 실패는 PASS로 덮지 않으며 다음 의존 배치를 막는다.
2. 같은 `batch_id`로 closeout report와 logall을 커밋 전에 한 번 마감한다.
   `run_id`까지 확인하며 다른 배치/예제의 로그 ID를 재사용하지 않는다.
   test-runner가 이미 같은 배치의 logall을 수행했으면 해당 산출물을 참조·보완한다.
   완료된 logall을 다시 호출하여 같은 내용을 중복 기록하지 않는다.
3. closeout에 검수·테스트·범위·남은 사항과 예정 통합 조치를 참조한다.
   아직 실행하지 않은 commit/push를 성공이나 실제 SHA로 적지 않는다.
4. closeout 전용 기록은 제품 후보 입력이 아님을 명시할 수 있다. 코드·권위 계약·
   평가 조건·필수 증거를 바꾸면 새 후보 검증·검수가 필요하다.
5. 승인된 파일과 동작만 커밋·push한다. 타인 변경을 stage/reset/stash/delete하지 않는다.
6. 실제 도구 결과로 commit SHA, 대상 remote/branch, push 결과, 작업 트리 상태와
   조회 시점을 통합 영수증에 기록한다. 비밀이 포함된 remote URL은 노출하지 않는다.
7. 자기 SHA를 해당 커밋 내용에 넣을 수 없으므로 사전 closeout에는 결과 참조를 두고,
   실제 SHA는 사후 실행 영수증·최종 응답 등 적절한 기록 위치에 남긴다.
   자기 SHA 갱신만을 위한 후속 커밋을 반복하지 않는다.

push가 미승인이고 요청 결과에 필수도 아니면 통합 부가필드에
`SKIPPED_WITH_REASON`과 근거를 적는다. 이를 성공한 push로 표시하지 않는다.
요청 결과에 필수인 push의 권한이 없거나 실행이 실패하면 `phase: BLOCKED`로 두고
원인·재개 조건을 기록하고 해당 릴레이를 멈춘다. 다음 배치를 시작하지 않는다.
커밋도 요청된 완료 조건과 권한에 맞게 처리하며 권한 없는 필수 통합을 생략 완료하지 않는다.

## 5. CLOSED와 reentry: 전체 목표까지 같은 루프 유지

- 배치 `CLOSED`는 해당 배치의 요구 closeout·통합 처리가 끝났다는 뜻이다.
  배치 종료만으로 전체 사용자 목표가 완료됐다고 선언하지 않는다.
- 메인은 기존 scope/acceptance/TODO를 다시 대조하고 남은 승인 범위 작업을 확인한다.
- 범위 안에 다음 작업이 있으면 동일 메인이 `DESIGN`으로 돌아간다.
  완료 배치의 참조를 보존하고 다음 배치 ID로 지시를 준비한 뒤 실제 dispatch한다.
- 새 root, 재귀 skill invocation, child relay로 재진입하지 않는다.
  relay 스킬을 읽고 적용하는 것과 별도 실행 루프를 다시 시작하는 것을 구분한다.
- 저장소에 남아 있는 범위 밖 TODO는 다음 작업으로 자동 채택하지 않는다.
  요청 목표가 충족됐다면 범위 밖 잔여 사항을 구분해 최종 보고한다.
- 차단된 의존 작업을 건너뛰어 다음 배치를 시작하지 않는다. 질문/검수 대기 중의
  안전한 독립 작업은 현재 DIRECTIVE 범위 안에서만 가능하다.
- 계속할 때 `continuation: CONTINUE_WITH_NEXT_FORM`과 다음 폼/실제 dispatch를 기록한다.
  배치별 완료 보고는 commentary/파일에 남기고 턴을 끝내는 final 응답은 보내지 않는다.
  목표 완료·범위 밖 다음 작업·실제 blocker·사용자 중단이면 `STOP_WITH_REASON`을
  기록하고 최종 응답한다. 스킬을 다시 읽는 것만으로 자동 재실행·예약된 재개가 생기지 않는다.

## 재시작과 완료 판단

재개 시 메인은 저장된 phase만 믿지 않고 실제 작업 트리, 후보 식별자, 검수 결속,
테스트 대상, closeout/logall 완료 기록과 commit/push 영수증을 대조한다.
실제 SHA·remote 상태를 확인해 이미 완료된 로그·커밋·push는 재실행하지 않는다.
상태와 실제 결과가 다르면 불일치를 기록하고 확인된 마지막 지점에서 이어간다.
전송만 된 메시지를 처리 완료로 추정하지 않으며 새 후보를 오래된 PASS에 연결하지 않는다.
최종 보고는 사용자 acceptance 충족 여부, 검증 근거, 실제 통합 결과와 남은 차단 사항을
구분한다. 필수 결과가 남았다면 whole goal complete로 보고하지 않는다.
