# BidFit Evidence-Harness v1-rc0 구현 원장

## 상태 (2026-09-03, Phase 0)

전체 구현은 진행 중이다. 완료된 P0를 이후 Evidence/검색/E1 앱 연결 완료로 취급하지 않는다.
브랜치 `feature/visual-retrieval`, 시작 HEAD `7ad229f`, 기존 사용자 dirty 변경 보존.

| 구분 | 결과 |
| --- | --- |
| 구현됨 | frozen runtime/eval DTO, fail-closed scope, typed predicate, versioned deterministic scorer, saved-answer replay CLI |
| 테스트됨 | 신규47 + 기존805 = 852 PASS / FAIL0 / ERROR0 / SKIP0 (32.147s) |
| 실제 실행 | 저장 답변129/source-case hash129 일치, 생성/API0, 새 private replay-03 (최종 코드 hash) |
| 별도 판정 | facts117 / atomic facts 없는12. 없는 분모를 perfect score로 바꾸지 않음 |
| 아직 미구현 | EvidenceStore/child dense+Kiwi/E1/전문 경로 통합/reranker/structured generation/layered evaluation |
| 실제 모델 실측 | 이번 Phase에는 없음. 기존 answer 재채점만 수행 |
| 성능 향상 주장 | 불가. 새 검색/생성 profile의 동일조건 A/B를 하지 않음 |

## 파일 / 책임

| 파일 | 역할 |
| --- | --- |
| `src/midprojectrag/runtime_integrity.py` | 닫힌 요청 스키마, deep immutability, runtime-only projection, scope/predicate |
| `src/midprojectrag/offline_harness/scoring.py` | 숫자/날짜/제한적 한국어/파일명/극성/부분 기권 scorer; semantic judge 아님 |
| `src/midprojectrag/offline_harness/replay.py` | 독립 case/hash join, 정답 원문/기존 답변 불변, private 출력 |
| `src/midprojectrag/offline_harness/__main__.py` | provider-free rescore 명령 |
| `tests/test_runtime_integrity.py` | gold lineage, mutation, empty guard, typed filter 회귀 |
| `tests/test_harness_scoring.py` | 표면형 동치, entity/숫자 연결, 부정/unknown, full filename, 기권 회귀 |
| `tests/test_harness_replay.py` | 저장 format, no-network, no-overwrite, stale source hash 회귀 |
| `scripts/check_harness_flow.cjs` | static flow 보고서 desktop/mobile 검증 |

## P0 수리 / 검증

- 평가 정답 key뿐 아니라 gold 값 변경 전후 runtime serialization/hash 불변을 검증한다.
- user scope와 gold ID의 우연한 문자열 일치를 차단하지 않는다. 입력의 출처가 경계다.
- `None`=unfiltered, empty=frozen zero match, nonempty=restriction. 공통 lane guard는 empty이면 호출하지 않는다.
- 미지원 field/operator와 유효하지 않은 숫자/date/list member는 explicit unsupported/unresolved다.
- 부정·확인불가 문장을 fact credit으로 인정하지 않는다. 단일 숫자라도 entity 연결을 검사한다.
- scorer가 의미의 완전한 동치를 증명하는 것은 아니다. 보수적인 false negative/paraphrase는 별도 semantic layer 대상이다.
- 판정 state는 gold 유무에 의존하지 않는다. 오류와 기권을 구별하고 전체 파일명을 접두/접미와 함께 보존한다.
- peer review 5개 지적을 수리한 뒤 원래 재현18개가 전부 PASS했다.

## 명령

```sh
PYTHONPATH=src .venv/bin/python -m unittest -q tests.test_runtime_integrity tests.test_harness_scoring tests.test_harness_replay
PYTHONPATH=src .venv/bin/python -m unittest discover -q -s tests -t .
PYTHONPATH=src .venv/bin/python -m compileall -q src/midprojectrag/runtime_integrity.py src/midprojectrag/offline_harness
bash scripts/validate_repo_safety.sh
PYTHONPATH=src .venv/bin/python -m midprojectrag.offline_harness rescore --help
```

실물 CLI는 저장된 local Mini131 `candidates.jsonl`과 독립 core40/rag56/set13/visual10/analytics10 case 파일을
`--cases`로 결합해 실행했다. 최종 출력은 `resources/data_refined/private/evaluation/bidfit-evidence-harness-v1-rc0/replay-20260903-03/`.
기존 replay-01/02는 보존했다. receipt에는 입력/case/code SHA, timestamp, counts를 담고 정답·답변 본문은 복제하지 않는다.

## Flow / 리스크 / 다음 릴레이

- flow: `../architecture/specs/bidfit-evidence-harness-v1-rc0-flow-validation.md` 및 HTML/MMD/PNG.
- Playwright: image2/table1/error0/mobile overflow0. UI 자체는 이번 Phase에서 변경하지 않았다.
- 초기 TDD red1, filename regression1, 실물 fact shape1, mobile overflow1은 모두 수리·재검증했다.
- 새 runtime DTO는 아직 기존 앱 query에 연결되지 않았다. 그 연결을 숨기지 않고 diagram에 GAP으로 표시했다.
- 다음 작은 작업: **EH1.1 Evidence/ProvenanceParent**, 이어 EH1.2 immutable store. score8의 상류 의존성.
- publication: 본 Phase 전용 source/tests/docs만 선택 stage한다. 사용자 기존 dirty와 resources는 제외한다.
