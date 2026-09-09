# OCR 그림 샘플 임베딩·검색 계약

이 문서는 최초 OCR 검색 단계의 기록과 아래의 후속 VLM 승인 범위를 함께 보존한다.
현재 실행 범위는 마지막 후속 승인·실측 항목을 따른다.

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

## 후속 승인 — 검색 그림을 VLM 답변에 연결 (2026-09-08)

### 목표·범위

사용자 요청: 위에서 설명한 OCR 검색 → 원본 그림 입력 → VLM 답변까지 실행한다.
기존 별도 CLI에 `answer` 동작을 추가한다. OCR 재실행/재임베딩 없이 같은 인덱스를 사용한다.
전체 corpus 확장, 이미지 픽셀 검색 임베딩, 사전 caption 임베딩, Streamlit 기본 bundle 변경은 제외한다.

### 계약

- 검색 top-1 occurrence만 전달. 검색 hit의 ID/citation/path를 index와 재대조하고 crop SHA를 다시 확인한다.
- 모델 입력은 질문 + 검증된 PNG 1장이다. OCR 본문은 모델에 전달하지 않아 실제 이미지 입력 여부를 구분한다.
- 기존 로컬 `mlx-community/Qwen3.5-9B-4bit` revision `8b2b98c00a6b4d291155e4890773ca8f769aee53`, MLX-VLM 0.7.0을 사용한다.
- 모델 manifest의 모든 파일 크기/SHA를 검사한다. vision_config와 Metal GPU가 없으면 중단. 새 다운로드 및 외부 API는 금지한다.
- MLX child는 OS network-denied subprocess, 고정 max_tokens 768, context 8192, temperature 0, thinking off, timeout 180초, 자동 재시도 0회다.
- 이미지 pixel tensor가 비어 있지 않음을 확인하고 그 tensor를 generate에 직접 전달한다. receipt에 tensor shape/입출력 token/device/model/prompt/hash/시간을 남긴다.
- VLM 출력은 answer:string, visible_details:string[], uncertainties:string[], abstained:boolean. JSON schema와 최대 길이를 검사한다.
- 이미지에 있는 지시는 데이터로만 취급하고 실행하지 않는다. 외부 지식으로 누락된 관계·숫자·이름을 채우지 않고 판독 불가를 표시하도록 요구한다.
- 답변은 `visual_inference`, `human_review_required=true`, `factual_evidence_promoted=false`다. 생성물을 원문/카탈로그/검색 인덱스에 다시 넣지 않는다.
- 보수적 QA gate: uncertainties가 하나라도 있으면 단정적 answer/visible_details를 출력 답변에서 보류하고 abstained=true로 반환한다. 원시 모델 응답은 private raw에 보존한다. 불확실성 미표시는 정답 보장이 아니다.
- 인용은 모델이 생성하지 않고 앱이 검증된 doc/page/bbox/crop에서 붙인다. 원본 위치 보장은 답변의 사실 정확성 보장과 다르다.
- request/raw/result/HTML은 새로운 private 출력 폴더에 0600으로 저장한다. 기존 파일 덮어쓰기 없음. 실패도 private 상태로 남기며 성공으로 포장하지 않는다.

### 구현·검증 배치

1. 별도 MLX 이미지 QA adapter + 기존 CLI answer 연결, 합성 계약 테스트.
2. 실제 질문 → KURE 검색 → PNG tensor → Qwen VLM → 답변/인용/HTML을 한 번 실행.
3. 기존 검색 회귀 및 자료 제외 검사, 같은 흐름 보고·TODO·로그 업데이트. 부모 평가 코드는 수정하지 않는다.

완료 기준: 실제 image tensor를 사용한 비어 있지 않은 답변과 출처가 저장되고, 오류/기권/변조/이미지 미입력 테스트가 통과한다.
정답 품질의 사람 검수와 브라우저 표시 검수는 별도이며, 기존 file URL 정책 차단을 우회하지 않는다.

### VLM 연결 실측·한계

- 합성/기존 회귀 39개 PASS. 텍스트만 입력·위조된 source·변경된 crop·모델/device/token 불일치·잘림·불확실성·worker 실패를 검사한다.
- 실제 호출 4회, 모두 검증된 PNG 1장만 사용. input pixel tensor `[1748,1536]`, `Device(gpu, 0)`, 별도 OCR 텍스트 입력 없음.
- 마지막 라벨 질문은 원본에 표시된 두 서버 이름/역할을 읽어 답했다. 입력 747토큰, 출력 76토큰, 순수 생성 2.125초, VLM 단계 7.537초, peak MLX 메모리 약 7.06GB.
- VLM 단계 시간에는 모델 SHA 검사·로딩·전처리·생성이 포함되지만 KURE 검색과 전체 CLI 시작 시간은 포함되지 않는다. 작은 smoke이므로 벤치마크/골든셋 점수가 아니다.
- 앞선 관계 질문 2회는 연결 부재 단정/없는 화살표 설명 등 오류가 관찰됐다. 프롬프트만으로 해결되지 않았고 품질 미통과로 남겼다.
- 3번째 응답은 불확실성 gate에서 실제 기권했다. 마지막 프롬프트는 질문에 필요한 정보만 답하도록 제한한다. 관계 정확성이 해결됐다고 주장하지 않는다.
- raw는 이전 진단 출력을 덮어쓰지 않고 보존한다. current answer 출력은 uncertainty가 있으면 보류한다. 사람 검수와 전체 corpus 평가를 통과하기 전 기본 RAG 근거로 승격하지 않는다.
- HTML은 기존 CSP/escape를 유지하며 원본 그림·OCR 검색 근거와 VLM 해석을 별도 구역에 둔다. 브라우저 검수는 기존 URL 정책 차단으로 미수행, 정적 검증으로 구분한다.
- 정적 QA PASS: 최신 답변/검증된 인용 일치, PNG 디코딩, 0600 권한, 흐름 PNG 2개. 이전 raw 3개를 현재 gate에 재적용하면 모두 기권한다. 저장소 safety 584파일 PASS.

### VLM 실행 방법

기존 build를 반복할 필요 없이 `answer`를 사용한다. 지정 MLX Python에는 MLX-VLM 0.7.0이 있어야 한다.
이번에는 이미 설치된 별도 MLX 환경과 고정 모델을 읽기 전용으로 재사용했고 새 패키지/모델을 설치하지 않았다.

```sh
python -m midprojectrag.indexing.visual_ocr_index answer \
  --private-root "$PRIVATE_ROOT" --index-dir "$PRIVATE_ROOT/ocr-index-v1" \
  --crop-root "$CROP_ROOT" --hf-cache "$HF_CACHE" --device mps \
  --query "$QUERY_TEXT" --result-dir "$PRIVATE_ROOT/vlm-answer-new" \
  --vlm-python "$MLX_PYTHON" --vlm-model "$VLM_MODEL_DIR" --vlm-manifest "$VLM_MANIFEST"
```

외부 네트워크 차단 wrapper는 위 OCR 실행 안내와 동일하다. VLM child에는 자체 OS sandbox도 적용한다.
`answer.json`은 계약과 source 재검증까지 통과한 완료 표식이다. `raw.json`은 정답이 아니라 진단용 생성 결과다.
`failure.json`이 있거나 완료 표식이 없으면 정상 답변으로 수용하지 않는다. `status=abstained`도 명시적 정상 종료 상태다.
