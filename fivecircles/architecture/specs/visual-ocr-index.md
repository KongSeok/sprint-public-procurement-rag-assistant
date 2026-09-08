# OCR 그림 샘플 임베딩·검색 계약

## 목표와 범위 — 2026-09-08

사용자 승인: 방금 확인한 그림 샘플의 OCR 청크를 임베딩하고 코드를 푸시한다.
`feat/vlm-visual-retrieval`의 별도 worktree에서 진행한다. Qwen 평가·원래 worktree·기존 인덱스는 수정하지 않는다.
공개 코드에는 범용 build/search CLI와 합성 테스트만 넣는다. 그림·OCR 본문·벡터·모델·실제 질의 결과는 resources/private 안에 둔다.

## 구현 계약

- 기존 visual-chunk-v1 검사기와 VisualExactDenseIndex를 재사용한다. OCR/layout만 허용하고 caption은 거부한다.
- occurrence ID, doc/page/bbox, crop hash와 실제 PNG를 재검증한다. 연결이 다른 청크는 임베딩 전에 거부한다.
- KURE-v1 고정 revision,1024차원,빈 prompt를 유지한다. 설치된 private 모델만 사용하며 다운로드·원문 외부 전송을 금지한다.
- 로컬 실측은 MCP terminal의 OS network-denied subprocess,명시적 MPS와 fallback 비활성화로 실행한다.
- 새 인덱스만 생성하고 기존 디렉터리는 덮어쓰지 않는다. chunks/vectors hash와 모델 identity를 metadata에 저장한다.
- reload 후 query도 같은 모델로 임베딩한다. 결과는 score,OCR text,doc/page/bbox,occurrence와 검증된 crop 경로를 포함한다.
- 동일 occurrence의 OCR/layout 중복은 화면 결과에서 하나로 묶는다. 원본 index row는 보존한다.
- private JSON/HTML 미리보기는 실제 검색 결과만 표시하고 텍스트를 escape한다. LLM 답변이나 구조 관계 해석은 생성하지 않는다.

## 완료 기준과 검증

1. 합성 단위 테스트: 계약·caption 차단·불일치 crop·중복·변조·덮어쓰기 거부·저장/reload/search.
2. 실제 샘플:2청크×1024차원 생성,MPS 실제 encoder 확인,새 프로세스 query가 같은 그림 occurrence를 반환.
3. 원본 입력의 전후 hash 동일,기존 Qwen 실행 코드 변경0,외부 API 호출0.
4. 흐름/검증 기록과 TODO 갱신,리소스 제외 확인,관련 파일만 커밋하고 같은 원격 브랜치로 fast-forward push.

## 비범위와 후속

전체 그림 재OCR,이미지 픽셀 임베딩,VLM 도식 해석,기존 Streamlit/LLM 파이프라인 통합,골든셋 정확도 판정은 이번 범위가 아니다.
이번 두 청크는 같은 그림이므로 검색 성공은 연결 smoke이며 corpus Recall/nDCG 증거가 아니다.

## 실행 결과

- 2026-09-08: 합성 persistence/provenance 12개와 기존 visual fusion/HF provider 12개, 총 24개 PASS.
- 기존 샘플 OCR/layout 2청크를 KURE-v1 1024차원으로 저장하고, 별도 프로세스에서 query를 임베딩하여 원본 그림 1 occurrence를 반환했다.
- 실제 encoder `mps:0`, CPU fallback 비활성화, OS network-denied subprocess. 모델 새 다운로드 및 외부 API 호출 없음.
- build 모델 로딩 4.668초 / 임베딩 0.812초. 새 프로세스 query 검색 0.454초(모델 로딩·인덱스 로딩·HTML 생성 제외). 단일 샘플 측정이지 처리량 벤치마크가 아니다.
- 원본 chunks/occurrences SHA 전후 동일, crop SHA 재검증. 실제 데이터·모델·벡터·미리보기는 Git 제외 resources/private에만 보존.
- 브라우저 file URL 검수는 도구의 URL 보안 정책으로 BLOCKED. 우회하지 않았으며, DOM/image-load 및 브라우저 screenshot PASS를 주장하지 않는다.
- 생성 미리보기는 query/citation/OCR escape, CSP, SHA 확인된 PNG data URI만 사용한다. 별도 CLI 연결만 검증했으며 Streamlit/생성 답변 경로는 그대로다.
- 정적 QA PASS: 2×1024 벡터 L2 정규화, source SHA 유지, 검색 occurrence 일치, HTML 내 PNG 디코딩, 공개 흐름 PNG 2개 및 필수 섹션 존재. 저장소 안전 검사 581파일 PASS.

## 재실행 방법

모델이 캐시된 로컬 환경에서 아래 CLI를 사용한다. `PRIVATE_ROOT`는 새 private 출력 루트,
`CROP_ROOT`는 기존 crops 폴더의 부모, `HF_CACHE`는 기존 Hugging Face private cache를 뜻한다.
실제 값은 Git 밖에서 설정한다. 입력 JSONL은 기존 visual pipeline의 출력 계약을 따른다.
실제 private 추론 프로세스에는 OS 수준 외부 네트워크 차단을 적용해야 한다.
Mac에서는 `/usr/bin/sandbox-exec -p '(version 1) (allow default) (deny network*)'` 뒤에
아래 실행 명령을 붙인다. offline 환경변수만으로 네트워크 차단이 보장되는 것은 아니다.

```sh
python -m midprojectrag.indexing.visual_ocr_index build \
  --private-root "$PRIVATE_ROOT" --index-dir "$PRIVATE_ROOT/ocr-index-v1" \
  --crop-root "$CROP_ROOT" --hf-cache "$HF_CACHE" --device mps \
  --chunks "$CHUNKS_PATH" --occurrences "$OCCURRENCES_PATH"
python -m midprojectrag.indexing.visual_ocr_index search \
  --private-root "$PRIVATE_ROOT" --index-dir "$PRIVATE_ROOT/ocr-index-v1" \
  --crop-root "$CROP_ROOT" --hf-cache "$HF_CACHE" --device mps \
  --query "$QUERY_TEXT" --result-dir "$PRIVATE_ROOT/query-001"
```

출력은 `metadata.json`, `vectors.npy`, 검증된 청크/occurrence 사본이다. 검색 출력은
`result.json`과 `index.html`이다. 기존 출력 디렉터리는 덮어쓰지 않는다.
CLI는 MPS가 없으면 중단한다. 일반 build/load/search 함수는 테스트용 provider 주입을 지원한다.

## 목표와 현재 흐름

목표: OCR 청크 → KURE 임베딩 → 별도 저장소 → 질문 임베딩 → 그림 출처/미리보기.
현재: 위 연결은 샘플로 실측 완료. 미리보기 브라우저 자동 검수만 정책 차단.
[목표 도형](visual-ocr-target-flow.mmd), [현재 도형](visual-ocr-current-flow.mmd),
[비교 HTML](visual-ocr-flow-validation.html).

| 항목 | 현재 | 다음 조치 / 우선순위 |
| --- | --- | --- |
| OCR 인덱스 저장/reload/검색 | 완료 | 유지, 0 |
| 그림 출처 hash/page/bbox | 완료 | 유지, 0 |
| 브라우저 이미지 표시 확인 | 자동 검수 차단 | 사용자가 private HTML 확인, 5 |
| 전체 그림 corpus 검색 품질 | 미평가·별도 범위 | 전체 대상과 평가셋 승인 후, 4 |
| Streamlit/LLM 근거 연결 | 이번 범위 제외 | 별도 통합 승인 후, 3 |
| 이미지 픽셀 임베딩/VLM 관계 해석 | 미구현·별도 범위 | 필요성 평가 후, 2 |

우선순위는 현재 납품 확인 3 + 직접 사용자 확인 2, 후속 범위는 효과 0~3 + 검증 준비 0~2로 산정했다.
초록은 검증된 경로, 노랑은 로컬 민감 자료, 빨강은 미연결/차단, 회색은 결정론 제어이다.
전체 RAG 목표 달성이나 골든셋 성능 개선을 이 결과로 선언하지 않는다.
