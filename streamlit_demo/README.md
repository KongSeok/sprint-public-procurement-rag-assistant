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
- 답변 하단에 `복합 조건 필터`/`RAG 생성` 처리 경로 표시

VLM 근거는 캐시된 결과만 재사용한다. 새로운 이미지를 실시간으로
판독하는 blind visual retrieval 서비스가 아니다.

## GCP 실행

레포 루트에 `.env`를 만든다.

```env
OPENAI_API_KEY=sk-...
BIDFIT_MODELS=openai:gpt-5-mini,openai:gpt-5-nano,future:qwen3-8b,future:qwen3.5-9b
```

`BIDFIT_MODELS`는 `provider:model` 형식의 화면 허용 목록이다. 현재 `openai`
항목만 실제 실행되고 `future` 항목은 로컬 백엔드 연결 위치를 미리 확보한
선택지다. 모델명만 OpenAI API에 보내는 잘못된 연결을 방지하기 위해 로컬
항목을 선택하면 실행 버튼이 비활성화된다.

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

## 필수 자산

- `output/chunks.pkl`
- `output/chroma_db/`
- `.env` 내 `OPENAI_API_KEY`

선택 자산:

- `output/experiments/b_plan_v3_vlm/visual_evidence.jsonl`

로컬 Qwen 백엔드는 이 앱에서 임의로 구현하지 않는다. 지수님이 제공할 통합
백엔드가 확정되면 `future` provider 처리부만 실제 클라이언트로 교체한다.

선택 자산이 없어도 텍스트 RAG는 정상 실행된다.

빠른 질문은 기존 `scripts/step24_prefilled_qa_prototype.py`의 검증된 후보
추출기를 재사용하고, AI 요약은 `scripts/step27_quick_answer_llm_polish.py`를
재사용한다. 기존 FastAPI 앱과 팀원 코드는 수정하지 않는다.

## 시연 주의사항

- 첫 실행에서는 KURE 모델과 Chroma DB를 불러오느라 시간이 걸릴 수 있다.
- 서버를 재시작해도 Chroma DB가 일치하면 기존 임베딩을 재사용한다.
- 시연 전에 예시 질문을 한 번씩 실행해 모델과 인덱스를 미리 로드한다.
- 외부에 포트를 공개하지 말고 SSH 터널을 사용한다.
