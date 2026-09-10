# TRAIN 학습셋 보강·폴더 정리 보고

- 기록 시각: 2026-09-10 13:56 KST
- 작업 위치: `vibe-workspace/vibe-workspace/sprint-public-procurement-rag-assistant`, `feat/hotline-runtime`
- 범위: 별도 승인된 사이드 작업의 학습 데이터 보강·정리·TODO·로그. 메인 채점 작업, 서비스 코드와 학습 실행은 제외했다.

## 결과

**기존157행에83행을 추가해240행을 별도 저장했다.** 240개 질문이 아니라 다음 행동 JSON 240개이며, 전체60궤적·54고유질문이다. 원본157행과 새 통합본의 첫157행은 동일하다.

| 신규 행의 출처 | 행수 | 해석 |
| --- | ---: | --- |
| 실제 로컬 MPS 검색 + 결정적 teacher | 6 | 실검색2개 시나리오. 실모델 정책 rollout 아님 |
| 기존 TRAIN 원문 근거 재생 | 36 | 새로운 벡터 검색·모델 추론으로 세지 않음 |
| 원문에 연결한 합성 상태 시나리오 | 41 | 명확화·검색 후 기권·진행/기억 관리 조건을 구성 |
| 합계 | 83 | 후보86행에서 내용 중복3행 제거 |

신규20시나리오 종료는 답변15·명확화3·기권2다. 새 행동은 검색28·읽기29·종료20·진행 조회1·진행 기록2·기억 조회1·메모2다. 새 문서나 TRAIN 가족이 늘었다는 뜻은 아니다.

## 폴더와 사용할 파일

비공개 루트: `resources/data_refined/private/training/evo35-train-augmentation-20260910-side-v3/`

- `release-v1/train-positive-sft.jsonl`: 통합240행. 현재 학습 설정에 자동 연결하지 않았다.
- `release-v1/new-action-sft.jsonl`: 신규83행.
- `release-v1/reviews.jsonl`, `summary.json`, `token-lengths.jsonl`: 채택/제외 이유·집계·토큰 길이.
- `records.jsonl`, `text-replay-v1/`, `followup-replay-v2/`, `synthetic-fixtures-v2/`: 현재 데이터의 실행 근거. 기존 경로를 유지했다.
- `archive/`: 초기 실검색 실패2폴더와 폐기된 합성 시범1폴더. 총9파일을 내용 변경 없이 옮겼으며 삭제0건.
- `archive/relocation-map.json`: 이전→현재 경로와 이동 전후 동일한 파일 해시.
- `scripts/`, `README.md`, `RUN_NOTES.md`: 재현 스크립트와 상세 인계.

원본은 별도 `Documents/ChatGPT/MidProjectRAG/evo35-training-data/resources/data_refined/private/training/evo35-3d-20260909/sft-v1-freeze/train-positive-sft.jsonl`에 보존했다. 해당 원본을 이동하거나 복제 작업본으로 덮어쓰지 않았다.

## TODO 반영

`EVO35.3d.AUGMENT.RUN`은 **부분 완료**로 유지한다. PACKAGE와 ORGANIZE_LOG는 완료이며, 아래는 남아 있다.

- 후보10개: 기관 역할 근거1·부분 근거 판정1·현 런타임 미지원 복구/빈 기억조회2·그림 픽셀/내용 검수6.
- INPUT: 새240행 입력·SHA 선택과 학습 설정 동결, 실제 trainer loss mask 및 자원 조건 확인.
- COLLECTOR_PATH: 실검색 수집기의 반복 전체 store 검증 확인. 이번2건은92.34/93.92초였고 속도 개선 완료로 보고하지 않는다.
- 실제 SFT와 non-golden DEV 비교는 기존 학습 TODO에서 이어간다. 골든 채점 결과로 이 보강 자료를 선택하지 않았다.

## 확인한 것과 하지 않은 것

기존 자료 생성 단계에서 신규83행의 원문/필드/문서/현재 핸들·상태를 검토하고 로컬 Qwen3.5 토크나이저의 템플릿 prefix·길이를 확인했다. 최대3358토큰이며 독립 사람 검수나 최종 답변 평가가 아니다.

이번 정리에서는 이동9파일과 최종 release6파일의 내용 보존, 파일 경로·링크·TODO 수치 및 Git 제외만 확인한다. 전체 회귀·골든 재채점·모델 재실행을 추가하지 않는다.

`training_ready=false`. 모델 학습0회, 외부 모델/API 호출0회, SEALED 실행0회다. 240행이 충분하다는 평가는 아직 하지 않았다. 정리 완료 시점에는 커밋·푸시를 하지 않았다. 이후 사용자가 데이터 없이 내용·경로의 게시만 별도 승인했다.

## 오류·재발 방지

- [수집 경로와 반복 검증](../test/errorlogs/backend/2026-09-10-training-collector-runtime.md)
- [수집 어댑터 요청 형식](../test/errorlogs/backend/2026-09-10-training-adapter-request.md)
- [재생·상태 시범의 근거 누락](../test/errorlogs/backend/2026-09-10-training-fixture-coverage.md)

원시 실패를 성공으로 덮지 않고 후속 성공은 새 버전으로 보존했다. 기관명이 등장한다는 이유만으로 발주기관 역할을 정답 처리하지 않았다.

## 공유 범위와 정확한 로컬 경로

이번 게시 대상은 이 보고서·관련 TODO·오류/재발방지·업데이트 로그뿐이다. 원문, 질문/답변, 학습 행, 모델·인덱스와 보강 스크립트는 게시하지 않는다. Git 문서를 받는 것만으로 학습 데이터가 내려오지는 않는다.

- 통합 학습 파일: `/Users/pio/vibe-workspace/vibe-workspace/sprint-public-procurement-rag-assistant/resources/data_refined/private/training/evo35-train-augmentation-20260910-side-v3/release-v1/train-positive-sft.jsonl`
- 집계·출처 구분: 같은 `release-v1/summary.json`.
- 원본157행: `/Users/pio/Documents/ChatGPT/MidProjectRAG/evo35-training-data/resources/data_refined/private/training/evo35-3d-20260909/sft-v1-freeze/train-positive-sft.jsonl`.
- 통합240행 SHA256: `a85c5b9ec526f41ac037d3d251a5e5ab810dee6fbf364121b9f7182544f10b25`.

원격 `feat/hotline-runtime`의 기준 커밋 `7aa56e9`에서 문서 변경만 분리했다. 로컬의 미푸시 코드 커밋 `dbebb51`, `240a6b6` 및 메인 작업의 다른 미커밋 변경은 이번 게시 범위에서 제외한다. 메인 작업폴더·브랜치는 변경하지 않는다. 실제 게시 결과는 Git 원격 조회로 별도 확인한다.
