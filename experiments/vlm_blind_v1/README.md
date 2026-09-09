# Blind VLM + scorer v3.1 experiment

이 실험은 기존 검색·생성 모델을 수정하지 않고 다음 두 항목만 검증한다.

1. Golden Set 보정 및 채점기 v3.1
   - `supplemental-set-b15`의 검수 후보 정답을 12개에서 15개로 보정
   - 답변 첫 문장에서 판단 불가를 밝히고 확인 가능한 배경을 설명한 응답을 기권으로 처리
   - 파일명 내부의 `[재공고]` 같은 대괄호 태그를 보존해 문서 ID 추출
2. 정답 위치를 사용하지 않는 시각 근거 연결
   - 기존 `HybridIndex`가 검색한 상위 문서만 후보로 사용
   - PDF 페이지와 HWP 내장 이미지를 후보화한 뒤 Qwen3-VL이 선택·판독
   - Golden Set의 정답 문서, page, bbox, object hash는 후보 생성과 VLM 호출에 전달하지 않음

GCP JupyterHub에서는 `notebooks/20260909_vlm_blind_v3_1_kongseok.ipynb`를
`myenv` 커널로 열어 위에서부터 실행한다. 결과와 실행 조건은
`output/vlm_blind_v3_1_runs/<run_id>/`에 저장되며 `output/`은 Git에 올리지 않는다.

이 버전의 B15 변경은 팀 검토 전 실행용 오버레이다. 공유 Golden Set 원본과
`review.status=draft`는 변경하지 않는다.
