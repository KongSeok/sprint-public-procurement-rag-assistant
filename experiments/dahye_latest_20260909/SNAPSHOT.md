# 생성 파이프라인 최신 스냅샷

- 원본 브랜치: `origin/feat/generation-pipeline-prompt-eval`
- 원본 커밋: `9c4429ee0963c76d1a08bfc06528e0c1349cb3c9`
- 스냅샷 일시: 2026-09-09
- 원본 파일: `src/generation/answer_generation.py`, `src/generation/generation_prompts.py`

원격 브랜치를 수정하지 않고 현재 `develop`에서 격리 실험하기 위해 복사했다.
패키지 경로만 맞추기 위해 `answer_generation.py`의 프롬프트 import를 상대경로로
변경했으며, 생성·검색·프롬프트 로직 자체는 원본 커밋과 동일하다.

## GCP 실행 파일

아래 네 파일을 GCP 레포의 같은 폴더에 업로드한다.

- `answer_generation.py`
- `generation_prompts.py`
- `run_golden_v3_latest.py`
- `run_golden_v3_latest.ipynb`

GCP 경로:
`/home/kongseok/sprint-public-procurement-rag-assistant/experiments/dahye_latest_20260909/`

노트북은 `myenv` 커널에서 위에서부터 실행한다. 기존 `output/chunks.pkl`,
`output/chroma_db`, `output/merged_docs.pkl`, `data/golden_set_v3/`,
`src/evaluation/scoring_v3/`는 이동하거나 복사하지 않고 현재 위치에서 재사용한다.
