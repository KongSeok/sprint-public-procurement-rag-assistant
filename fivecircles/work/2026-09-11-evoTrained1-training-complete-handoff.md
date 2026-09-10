# evoTrained1 — 완료 학습본과 전체131 실행 인계

기록일: 2026-09-11 KST. 사용자 요청 순서: **기록·푸시 먼저 → 완료 학습본 연결 → 전체131 실행**.

## 현재 결론

학습은 **111스텝·3에폭 완료**다. 다음 평가 후보는 마지막111이 아니라 내부 monitor loss가 가장 낮은 **checkpoint108 / best-adapter**다. 두 위치의 어댑터 가중치 SHA256이 일치함을 확인했다. 골든10 결과를 보고 체크포인트를 고른 것이 아니다.

앞서 같은10문항 OFF/ON 비교에 사용한 것은 **중간 checkpoint38**이다. 그 결과를 완료본108의 성능으로 바꾸어 적지 않는다. 전체131 새 실행, 완료본 VM 전송·활성화는 이 기록 시점에 **미시작**이다.

## 학습 완료 근거

| 항목 | 확인값 |
| --- | --- |
| 실험 | `aug399-es10-ab87aec5` |
| 학습 / 내부 검증 | 292 / 107행, 총399행 |
| 매번 확인한 검증 범위 | 내부 검증에서 고정한 monitor12행 |
| 종료 | `COMPLETED`, `EPOCH_LIMIT`, step111, epoch3.0 |
| 장치 | MPS — 학습 장치이며 VM 추론 CUDA와 구분 |
| 내부 monitor 최적점 | checkpoint108, loss `0.048756033182144165` |
| 전체 내부 검증107행 | `NOT_REQUESTED` — monitor12 점수를 전체 검증으로 확대하지 않음 |
| 별도 RAG 품질·DEV gate | 미통과/미실행 상태 유지, 운영 서빙 활성화 없음 |

학습 receipt SHA256: `e430c2a4b19fc9386a51f953705d7f1b4674a40e3dff000d9a11f84abe0f0254`.

checkpoint108와 best-adapter의 `adapter_model.safetensors` 공통 SHA256:
`a5aca57a2e0059177515d5ee4cd46b5bd80e3fa8bf928bcc81d69d0fdc9f3ece`.

이 해시는 가중치 동일성을 확인한 것이다. tokenizer·설정·VM 패키지 전체 검증 및 추론 성공을 대신하지 않는다.

## 저장 위치

로컬 저장소: `/Users/pio/vibe-workspace/vibe-workspace/sprint-public-procurement-rag-assistant`.

아래 경로는 저장소 루트 기준이며 모두 `/resources/` Git 제외 정책을 유지한다.

```text
resources/data_refined/private/training/evo35-train-augmentation-20260910-side-v3/
  earlystop-experiments/aug399-es10-ab87aec5/
    segments/run-1789050320482010000/attempt-mps/
      training-receipt.json
      checkpoints/checkpoint-108/
      checkpoints/checkpoint-111/trainer_state.json
      best-adapter/

resources/data_refined/private/evaluation/evoTrained1-paired10-c38-20260911-001/
  paired-final.json
  paired-case-metrics.csv
  semantic-records.jsonl
  validation-receipt.json
```

기존 VM 환경 루트: `/home/pio/evo35-cuda-test-20260910`.
checkpoint38 비교 결과는 그 아래 `evaluations/paired10-c38-20260911-001/{off,on}`에 있으며, 완료본108의 전송 목적지·새 run ID는 다음 실행 때 별도로 고정한다.

## 이미 끝난 비교 — checkpoint38만 해당

동일10문항을 OFF/ON 각각 새로 생성했다. 답변2→3, 예비 정답 통과2→2, 런타임 실패4→1, 평균42.03→47.34초다. 안정성 변화는 관측됐지만 정답률·속도 개선이나 운영 승격은 입증되지 않았다.

의미 채점은 비블라인드 예비 검토다. 실제 reviewer 모델 ID 미확인으로 공식 독립검수 완료를 선언하지 않는다. 검색 @k는 공통 관측 분모로 비교하고 무응답 의미점수는 null로 보존했다.

[10문항 비교 보고서](2026-09-11-evoTrained1-paired10-comparison.md) · [실패·추출기 수정 기록](../test/errorlogs/backend/2026-09-11-evo-paired10-capture.md)

보고서 VM 복사는 추가 사용자 승인 후 완료됐다. 위치는 `/home/pio/evo35-cuda-test-20260910/paired10-c38-20260911-001-report.md`, 9,179bytes, 로컬/VM SHA256 `8ca729c18db992314483af0a2a70f97ca278b9836bd09c2f976591dd47afcb2e` 일치. 복사 당시 차단 이력은 삭제하지 않고 해결 상태를 덧붙였다.

## 다음 실행 — 아직 결과 없음

1. 기록을 먼저 원격 `feat/hotline-runtime`에 게시한다. 메인 체크아웃·미커밋 코드와 학습 원본은 건드리지 않는다.
2. 완료본108의 실행 파일만 새 VM snapshot으로 고정하고 같은9B CUDA/NF4 정책 LoRA에 연결한다. 기존38 결과·스냅샷은 보존한다.
3. 기존 골든 inventory **131개 = 질답129 + 파서 검사2**를 유지해 새 실행한다. 미지원·실패도 원장에 남기며 기존131 답변을 새 생성으로 재사용하지 않는다.
4. 기존 채점 기준으로 유형별 답변·실패·검색·의미·시간을 보고한다. 모델/데이터/코드가 다른 과거 결과는 동일조건 paired 성적으로 합치지 않는다.

현재 완료본108 패키징·전송, 전체131 runner의 VM 연결 준비 여부는 아직 확인 전이다. 이 문서는 그 실행을 완료·통과 처리하는 문서가 아니다. 골든 질문·정답·실패를 TRAIN이나 튜닝 입력으로 옮기지 않는다.

## 이번 게시 범위와 점검

새 비교 보고·학습 완료 인계·관련 TODO/로그만 공개한다. 원문·질답·학습행·가중치·키·실험 실행 코드는 이번 기록 커밋에 넣지 않는다.

기존 실행 receipt·완료 상태·가중치/보고서 해시·Git 제외 여부만 확인했다. 재학습·재생성·전체 회귀·VM 설정 변경은 하지 않았다. 푸시 성공은 실제 원격 tip 확인 후 별도로 알린다.
