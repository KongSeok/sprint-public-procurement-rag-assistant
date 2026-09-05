# 단계별 근거 평가 독립 리뷰

2026-09-05 · root + review_early_eval + review_eval_gate

범위: stage_metrics.py, stage_checkpoints.py, stage_evaluation.py 및 대응 tests, stage-evaluation-v1 계약.

| 발견 | 수리 | 재검토 |
| --- | --- | --- |
| P1: 131 sidecar 중 행 누락 시 부분 결과가 전체처럼 보일 수 있음 | CLI 기본 mini131 suite별 수량 강제, partial은 complete=false | 해결 확인 |
| P2: 전용 suite 자유 명칭으로 텍스트 평균 혼입 가능 | suite 6종만 허용, 전용 suite ready 거절 | 해결 확인 |

판정: **코드 APPROVE**, 추가 correctness blocker 없음. source 파일 SHA/owner/locator,
checkpoint chain/store 일치, 분모0/null, 중복 raw rank, context 근거 손실과 양방향 rescue 확인.
집중·관련112 PASS. 기존 runtime·VLM·API·골든 질문/답변은 수정하지 않았다.

한계: source-block 점수는 정확한 문장/구간 완전성이 아니다. snapshot/hash는 offline consistency이며
live owner authority를 증명하지 않는다. 실제 전체131 위치 sidecar/단계 기록/성능 비교는 미실행이다.
131 case ID/의미 정답 검수는 기존 검수와 qrel hash 계약을 따른다. count guard가 의미 검수를 대체하지 않는다.
보고서 HTML 브라우저 QA는 file URL 정책으로 BLOCKED이며 코드 승인과 별개로 기록한다.
