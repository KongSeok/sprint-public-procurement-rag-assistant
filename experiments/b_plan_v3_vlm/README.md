# B-v3 선택적 로컬 VLM 통합

B-v2의 하이브리드 검색·생성 경로를 유지하면서, 문서 텍스트에 정보가 없는
구성도/그림 질문에만 로컬 VLM 시각 근거를 추가하는 분리 실험이다. 표 질문은
기존 구조화 텍스트를 계속 사용한다. 이는 OCR/layout을 먼저 쓰고 복잡한 도식에만
VLM을 적용하라는 `feat/vlm-visual-retrieval`의 설계를 따른다.

## 범위와 안전장치

- 가져온 설계 기준 브랜치: `feat/vlm-visual-retrieval` (`5c732eb`)
- 직접 VLM 모델: `Qwen/Qwen3-VL-8B-Instruct` 로컬 vLLM 서버
- 골든 정답·필수 사실은 VLM 프롬프트에 넣지 않는다.
- 원본, 렌더 이미지, VLM 판독문, 상세 답변은 모두 `output/` 아래에 두며 Git에 올리지 않는다.
- PDF는 골든셋이 지정한 page/bbox만 렌더한다.
- 각 시각 근거에 evidence ID, 원본 문서 SHA-256, 이미지 SHA-256, page/bbox와
  provenance 수준을 함께 기록한다. 생성 프롬프트에도 같은 근거 표식을 전달한다.
- HWP는 정확한 페이지 렌더러가 없으므로 문서에서 추출한 큰 이미지 후보를 제한적으로 비교한다.
  평가셋에 대상 객체 SHA-256이 있고 추출 이미지와 정확히 일치하면 해당 이미지를 직접 연결하고
  `gold_target_object_hash_verified`로 표시한다. 일치하지 않을 때만 후보 contact sheet의
  2단계 선택을 사용한다. 전자는 생성 단계 검증이며 시각 검색 점수로 계산하지 않는다.
- PDF 그림은 지정 bbox의 확대본과 같은 물리 페이지 전체를 한 context sheet로 묶어,
  잘린 영역 때문에 그림 관계의 한쪽이 사라지는 문제를 줄인다.
- 시각 브랜치의 Evidence-Harness 및 별도 평가 구조는 포함하지 않는다.

## 실행 순서

```bash
source ~/myenv/bin/activate
python -m experiments.b_plan_v3_vlm.prepare_visual_inputs
```

기존 텍스트 vLLM 서버를 잠시 내린 뒤 별도 환경에서 로컬 VLM을 실행한다.

```bash
source ~/vllm-venv/bin/activate
vllm serve Qwen/Qwen3-VL-8B-Instruct \
  --host 127.0.0.1 \
  --port 8003 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 4096 \
  --limit-mm-per-prompt.image 8
```

다른 터미널에서 시각 근거를 생성하고 visual 10문항을 평가한다.

```bash
source ~/myenv/bin/activate
python -m experiments.b_plan_v3_vlm.run_visual_vlm
set -a
source ~/.openai-eval.env
set +a
python -m experiments.b_plan_v3_vlm.run_visual_golden
```

결과 경로:

- `output/experiments/b_plan_v3_vlm/visual_evidence.jsonl`
- `output/experiments/b_plan_v3_vlm/visual_golden_results.csv`
- `output/experiments/b_plan_v3_vlm/visual_summary.json`

## 해석 제한

이 실험은 실제 VLM 판독을 추가하지만, HWP 전체의 page/bbox 기반 occurrence 복구를
완성하는 실험은 아니다. 특히 HWP 후보 방식의 성공을 완전한 시각 검색 성공으로
확대 해석하면 안 된다. PDF 대상은 지정된 영역을 사용하므로 더 강한 근거를 가진다.
