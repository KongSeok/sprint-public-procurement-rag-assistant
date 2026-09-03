# EH-RC0 재개 체크포인트

갱신: 2026-09-03 · Phase 0 구현·검증 완료. 토큰 절약을 위해 `bidfit-evidence-harness-v1-rc0-active-context.md`부터 읽기.

## 중단/애매함 발생 시

- 짧은 재개 안내: `bidfit-evidence-harness-v1-rc0-resume.md`.
- private snapshot: `resources/context-backups/eh-rc0-context-20260903-165754-737633.zip` (repo 기준).
- 24파일 / 389,435 bytes. SHA-256: `63afe3171b138d099f6bba62fb4cf32ef535232f32629b6bd8769830382f99f9`.
- ZIP의 `START-HERE.md` → snapshot checkpoint → 필요한 계약/원문 절 순서로 읽는다.
- ZIP은 2026-09-03 16:57:54 KST의 문서 스냅샷이다. 최신 live checkpoint/사용자 지시와 대조한다.
  전체 대화/코드/dirty 변경 백업은 아니며 live repo 위에 덮어쓰지 않는다.

## 한눈에 보는 상태

- 전체 목표: BidFit Evidence-Harness v1-rc0. 목표 축소/완료 처리 없음.
- 실행 방식: 사용자 요청에 따라 leaf 하나씩 순차 처리. 새 독립 책임이 나타나면 해당 leaf를 다시 분할.
- repo: `/Users/pio/Documents/AIENGINEERCOURSE/MidProjectRAG` (ambient ChatGPT 사본 사용 금지).
- branch / 시작 HEAD: `feature/visual-retrieval` / `7ad229f8c85fb48ebb1c53f4424db4a224b562a7`.
- 완료: EH-A.1~3 감사·기준선·계약/flow 초안. 805 tests PASS, 실패/skip 0 (변경 전).
- 현재 IN_PROGRESS: Phase 0 선택 publication. 다음 READY: **EH1.1**.
- blocker: 현재 첫 leaf에는 없음. Kiwi/child artifact/Qwen/API 실측 가용성은 해당 leaf에서 확인.
- 코드 상태: runtime integrity/offline_harness 신규 구현. focused 47/전체 852 PASS; 원샷 전체는 미완료.

## 완료된 첫 leaf 참고: EH0.1.a (현재 작업 아님)

- 목표: runtime 입력 allowlist와 evaluator-only 필드의 hard boundary를 테스트로 고정.
- 읽을 것: TODO의 EH0.1, 계약 §8.1~8.2, `src/midprojectrag/answering/pipeline.py`의 request 사용부.
- 수정 허용: 신규 `src/midprojectrag/runtime_integrity.py`, `tests/test_runtime_integrity.py`.
  먼저 public DTO signature/테스트만 고정; projection 구현은 EH0.1.b에서 마무리.
- 검증: `PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_runtime_integrity`.
- 판정: allowlist 밖 gold/qrels/required_doc_ids/reference/expected 및 임의 중첩 options를 runtime에 전달 불가.
  정상 user scope와 gold ID가 우연히 같은 값인 경우를 문자열 blacklist로 차단하지 않는다.
- 실패 테스트를 먼저 남길 경우 EH0.1.a의 red evidence로 명시한다. green 구현/푸시/완료 주장은 EH0.1.b~c 뒤에 한다.
- 다음 후보: EH0.1.b → EH0.1.c → EH0.2. 전체 tree는 `../architecture/todolist.md#eh-rc0--evidence-harness-재귀-실행-todo-2026-09-03`.

## 매 leaf 종료 시 갱신할 최소 항목

`ID | 상태 | 변경 파일 | focused 명령/결과 | 새 결정·남은 실패 | 다음 ID/선행조건`

새 완료 행은 아래 원장에 한 줄 추가하고 현재 READY만 이동한다. 새로 시작할 때 완료한 감사,
805-test baseline, 리서치 문서 전체를 다시 실행/읽지 않는다. 코드 영향이 있는 Phase gate에서만 전체 검증한다.

## 완료 원장

| ID | 결과 | 근거 |
| --- | --- | --- |
| EH-A.1 | COMPLETED | 원샷 기록의 시작 감사 스냅샷; dirty 사용자 변경 보존 |
| EH-A.2 | COMPLETED | unittest discover 805 tests / 33.493s / OK / skip 0 |
| EH-A.3 | COMPLETED | 계약+target/current MMD/PNG/HTML 초안; browser QA는 EH-D.3 |
| TODO-SPLIT | COMPLETED | Phase 0~4+납품을 독립 leaf/의존성/gate로 분해; 구현 동시 실행 1개; read-only 의존성/acceptance 리뷰 및 diff-check PASS |
| EH-CONTEXT.1 | COMPLETED | private ZIP 24파일; CRC/SHA/원문 동일성/기존 문서 불변/Git 제외 검증; 다음 leaf EH0.1.a 유지 |
| EH0.1~7 / EH0.G | COMPLETED | focused47/full852, 0 skip; case SHA129/129 provider-free replay; review18/18, HTML desktop/mobile PASS |

## 안전/컨텍스트 규칙

- 원래 tracked dirty 39개와 다수 untracked 파일은 사용자 소유다. broad add/reset/checkout/merge 금지.
- `resources/` 전체 비공개. gold/원문/벡터/key/private trace를 공개 로그로 복사하지 않는다.
- 기존 artifact overwrite 금지. 실제 모델 호출/임베딩은 해당 별도 leaf에서만 실행한다.
- 완료 체크는 test/receipt에 근거한다. code complete ≠ real run ≠ quality validated.
