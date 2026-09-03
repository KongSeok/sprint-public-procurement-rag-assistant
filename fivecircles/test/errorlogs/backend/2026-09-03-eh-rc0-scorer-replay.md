# EH-RC0 scorer/replay repairs

- Timestamp: 2026-09-03 17:18:23 KST (기록 시각)
- Paths: offline_harness/scoring.py, replay.py
- Code: ASSERTION_FAILURE / UNSUPPORTED_FACT_GROUP_SHAPE
- Messages: `other-report.hwp` suffix가 전체 파일명으로 오인됨; 실물 core40 point_id/text atom shape 미지원.
- Fix: filename 선행 boundary에 hyphen/dot 포함; 명시적 point_id/text adapter 및 regression 추가.
- Verification: focused 43 PASS; 전체 848 PASS; 실제 129-row replay/hash 129/129, 모델 호출 0.
- Prevention: 합성 string group만 검사하지 않고 실물 key/type를 비식별 검증; corpus 본문은 로그에 노출하지 않음.

## Peer-review repair (2026-09-03 17:24 KST)

- 발견: 부정/확인불가 문장 사실 credit, 단일 숫자 entity 오매핑, filename 접두·접미, gold-dependent 기권, 잘못된 filter scalar.
- 수정: assertion/극성·unknown guard, 항상 entity binding, filename boundary, gold-independent sentence state, typed scalar/date/range validation.
- 검증: focused 47 PASS, 기존 replay-01 보존, scorer code hash가 있는 replay-02에 129건 재채점.
