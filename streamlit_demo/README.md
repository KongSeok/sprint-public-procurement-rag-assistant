# 통합 RAG Streamlit 시연

기존 문서별 Streamlit/FastAPI 프로토타입을 수정하지 않고, `develop`에
분리한 전체 RFP 검색 시연 앱이다.

## 연결 범위

- `output/chunks.pkl`의 전체 문서 청크
- KURE 벡터 검색 + BM25 `HybridIndex`
- Parent-Child 컨텍스트 확장
- `experiments/dahye_latest_20260909.answer_generation.ask_rfp_v9`
- `output/experiments/b_plan_v3_vlm/visual_evidence.jsonl` 기존 Qwen3-VL 근거
- 최종 인용의 VLM 내부 ID 제거 및 실제 `doc_id` 유지
- 전체 98개 문서 / 직접 선택 / 메타데이터 조건 검색 범위
- GPT-5 mini, GPT-5 nano 실행
- Qwen3 8B, Qwen3.5 9B 선택 UI(로컬 백엔드 연결 전 비활성)
- 단일 문서 선택 시 예산·일정, 발주기관, 서식, 참가자격 등 11종 빠른 질문
- 규칙 기반 후보 표시, 후보 원문 확장, 선택적 AI 요약
- 기간과 예산이 함께 지정된 복합 목록 질문의 모든 조건 적용
- 최근 게시·공개된 공고와 예산을 함께 지정한 복합 목록 질문 지원
- 답변 하단에 `복합 조건 필터`/`RAG 생성` 처리 경로 표시
- 전체 검색 모드에서도 별도로 문서를 선택해 11종 빠른 질문 사용
- `5억 이상 20억 미만`처럼 예산 하한·상한을 함께 지정하는 범위 검색
- 전체 문서 찾기와 문서 한 건 빠른 검토를 별도 화면으로 분리
- 빠른 질문 누적 기록, AI 요약 실패 재시도, 문서 범위 자유 질문과 근거 보기

VLM 근거는 캐시된 결과만 재사용한다. 새로운 이미지를 실시간으로
판독하는 blind visual retrieval 서비스가 아니다.

## GCP 실행

레포 루트에 `.env`를 만든다.

```env
OPENAI_API_KEY=sk-...
BIDFIT_MODELS=openai:gpt-5-mini,openai:gpt-5-nano,qwen3-8b:Qwen/Qwen3-8B,qwen3.5-9b:Qwen/Qwen3.5-9B,qwen3.5-27b:Qwen/Qwen3.5-27B
BIDFIT_QWEN3_8B_URL=http://127.0.0.1:8002/v1
BIDFIT_QWEN35_9B_URL=http://127.0.0.1:8003/v1
BIDFIT_QWEN35_27B_URL=https://PERSONAL-MODEL-ENDPOINT.example/v1
BIDFIT_LOCAL_MODEL_API_KEY=서버에_설정한_키_또는_local-model
BIDFIT_DEMO_PASSWORD=팀에서_정한_암호
```

`BIDFIT_MODELS`는 `provider:model` 형식의 화면 허용 목록이다. Qwen 항목은
vLLM 등의 OpenAI 호환 `/v1` 서버 주소를 각 환경변수로 받는다. 서버가 꺼져
있거나 주소가 없으면 해당 모델은 실행되지 않는다. L4에서 8B와 9B를
동시에 띄울 수 있다고 가정하지 않으며, 개인 PC의 27B는 해당 PC와 HTTPS
엔드포인트가 켜져 있을 때만 사용할 수 있다.

## SSH 터널 없는 임시 팀 시연

`.env`에 `BIDFIT_DEMO_PASSWORD`를 설정한 뒤 VM에서 Streamlit을
기존처럼 `127.0.0.1:8010`에 실행한다. 두 번째 VM 터미널에서 실행한다.

```bash
bash scripts/share_streamlit_demo.sh
```

출력된 `https://....trycloudflare.com` 주소를 공유하면 팀원은 SSH 없이
브라우저로 접속할 수 있다. 이 임시 주소는 터널을 다시 실행하면 바뀐다.

```bash
cd ~/sprint-public-procurement-rag-assistant
source ~/myenv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_demo/app.py \
  --server.address 127.0.0.1 \
  --server.port 8010
```

로컬 PowerShell에서 SSH 터널을 열고 `http://127.0.0.1:8010`으로 접속한다.

```powershell
ssh -i "$env:USERPROFILE\.ssh\id_ed25519_rag_vm" `
  -L 8010:127.0.0.1:8010 `
  kongseok@<VM_EXTERNAL_IP>
```

여러 팀원이 함께 시연하는 절차는
[`docs/streamlit-team-demo.md`](../docs/streamlit-team-demo.md)를 참고한다.

## 필수 자산

- `output/chunks.pkl`
- `output/chroma_db/`
- `.env` 내 `OPENAI_API_KEY`

선택 자산:

- `output/experiments/b_plan_v3_vlm/visual_evidence.jsonl`

로컬 Qwen은 Streamlit 프로세스 안에서 모델을 직접 로드하지 않고, 별도의
OpenAI 호환 추론 서버에 연결한다.

선택 자산이 없어도 텍스트 RAG는 정상 실행된다.

빠른 질문은 기존 `scripts/step24_prefilled_qa_prototype.py`의 검증된 후보
추출기를 재사용하고, AI 요약은 `scripts/step27_quick_answer_llm_polish.py`를
재사용한다. 기존 FastAPI 앱과 팀원 코드는 수정하지 않는다.

## 시연 주의사항

- 첫 실행에서는 KURE 모델과 Chroma DB를 불러오느라 시간이 걸릴 수 있다.
- 서버를 재시작해도 Chroma DB가 일치하면 기존 임베딩을 재사용한다.
- 시연 전에 예시 질문을 한 번씩 실행해 모델과 인덱스를 미리 로드한다.
- 링크 공유 시 `.env`의 `BIDFIT_DEMO_PASSWORD`를 반드시 설정한다.
