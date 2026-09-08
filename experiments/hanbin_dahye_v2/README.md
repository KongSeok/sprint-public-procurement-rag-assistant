# Hanbin–Dahye B-v2 experiment

한빈님의 Hybrid Retrieval과 다혜님의 2026-09-08 최신 Generation 파이프라인을
Golden Set v3 79문항으로 평가하는 분리 실험이다. B-v1 코드와 결과를 덮어쓰지
않는다.

## 출처

- Retrieval: `feat/rag-pipeline-and-eval`의 `d51633b`
- Generation 함수: `feat/generation-pipeline-prompt-eval`의 `647931b`
- Generation 프롬프트: 같은 브랜치의 `f028e5f`
- 제외: `uyt5041-lab`의 Evidence-Harness 및 관련 평가 구조

`answer_generation.py`와 `generation_prompts.py`는 위 다혜님 브랜치의 파일을
이 폴더로 복사했다. 패키지 내부에서 동작하도록 프롬프트 import 경로만 상대
경로로 바꿨으며, 생성·검색 분기 로직과 프롬프트 본문은 변경하지 않았다.

## 실행

저장소 루트에서 실행한다.

```bash
source ~/myenv/bin/activate
python -m experiments.hanbin_dahye_v2.run_golden_v3
```

중단된 실행은 다음 명령으로 이어서 진행할 수 있다.

```bash
python -m experiments.hanbin_dahye_v2.run_golden_v3 --resume
```

기본 결과 경로:

- 상세 결과: `output/experiments/hanbin_dahye_v2/golden_v3_results.csv`
- 집계 결과: `output/experiments/hanbin_dahye_v2/summary.json`

상세 CSV에는 질문과 생성 답변이 있으므로 공개 저장소에 커밋하지 않는다.

## 반복 실행 재현성 분석

4회 결과가 준비된 뒤 다음 명령으로 실행 간 평균·표준편차·범위와 문항별 판정
변동 수를 계산한다.

```bash
python -m experiments.hanbin_dahye_v2.analyze_reproducibility
```

집계 결과는 `output/experiments/hanbin_dahye_v2/reproducibility_summary.json`에
저장한다.
