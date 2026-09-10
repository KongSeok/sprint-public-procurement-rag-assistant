# 서빙 앱 배포 가이드 (Docker + GCP VM)

`app/`(FastAPI + 웹 UI)을 팀이 이미 쓰는 GCP VM에 상시 컨테이너로 띄우는 방법입니다.

## 왜 이 구조인가

버셀 같은 서버리스에 올리는 방안을 먼저 검토했는데, 서버리스는 요청 사이에 메모리와
상태가 유지되지 않습니다(도커 이미지를 받아주는 경우에도 내부적으로는 함수로 감싸서
돌리고, 유휴 상태가 되면 인스턴스가 내려갑니다). 이 파이프라인은 KURE-v1 임베딩
모델(약 2.2GB)을 한 번 올려두고 계속 재사용하는 걸 전제로 하기 때문에 그 모델과 맞지
않아서, **상시 떠 있는 컨테이너**로 방향을 잡았습니다.

무거운 것들은 이미지에 굽지 않고 VM 호스트의 폴더를 볼륨으로 마운트합니다. 코드를
고쳐서 이미지를 다시 빌드해도 인덱스나 모델을 다시 만들 필요가 없습니다.

| 컨테이너 안 | VM 호스트 | 용도 |
| --- | --- | --- |
| `/app/data` (읽기 전용) | `./data` | 원본 CSV, 사람이 확정한 override 파일 |
| `/app/output` | `./output` | 전처리 캐시(`merged_docs.pkl`, `chunks.pkl`) |
| `/root/.cache/huggingface` | `~/.cache/huggingface` | KURE-v1 모델 다운로드 캐시 |

## 준비물

VM에 Docker와 Compose 플러그인이 있어야 합니다.

```bash
docker --version && docker compose version
```

없으면 `sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin` 후
`sudo usermod -aG docker $USER` (재로그인 필요).

그리고 레포 루트에 아래 두 캐시가 있어야 합니다. **서버는 원본 hwp/pdf를 직접
재파싱하지 않습니다** — 수 시간짜리 배치 작업이라 서빙 중에 할 일이 아니라고 보고,
없으면 안내 메시지를 띄우고 멈추게 해뒀습니다.

```
output/merged_docs.pkl   # python scripts/step2_merge_text.py
output/chunks.pkl        # python scripts/step3_chunking.py
```

## 실행

```bash
cd ~/sprint-public-procurement-rag-assistant
git pull

# API 키 (없으면 버튼 패널만 동작하고 AI 요약/자유 질문은 "키 없음"으로 안내됨)
echo "OPENAI_API_KEY=sk-..." > .env

docker compose up -d --build
docker compose logs -f          # Ctrl+C로 로그만 빠져나옴 (컨테이너는 계속 실행)
```

기동 자체는 몇 초면 끝납니다 — 무거운 자원은 전부 지연 로드라, 컨테이너가 뜨는
시점에는 아무것도 안 읽습니다.

- 코퍼스(`merged_docs.pkl`)는 **첫 요청** 때 한 번 읽습니다(수 초).
- 임베딩 모델은 **자유 질문을 처음 던졌을 때만** 로드합니다. 즉 버튼 패널만 쓸 거면
  2GB 모델을 아예 안 올립니다.
- 그래서 **자유 질문 첫 한 번은 느립니다**. 모델 캐시가 비어 있으면 HuggingFace에서
  2.2GB를 받느라 회선에 따라 몇 분 걸릴 수 있고, 그다음부터는 캐시가 남아 빠릅니다.
  미리 받아두려면 컨테이너 안에서 한 번 로드해두면 됩니다:
  ```bash
  docker compose exec bidfit python -c "from src.retrieval.embeddings import get_default_embedding_backend as g; g()"
  ```

## 접속

기본은 `http://<VM-외부IP>:8000` 입니다. 단, GCP는 기본적으로 8000 포트가 막혀 있어서
방화벽 규칙을 열어야 합니다.

```bash
gcloud compute firewall-rules create allow-bidfit-8000 \
  --allow tcp:8000 --source-ranges 0.0.0.0/0 --target-tags bidfit
gcloud compute instances add-tags <VM이름> --tags bidfit --zone <존>
```

**팀 내부 데모라면 포트를 열지 않는 쪽을 권합니다.** 이 앱에는 로그인/인증이 전혀
없어서, 열어두면 URL을 아는 누구나 RFP 원문과 API 키로 도는 답변 생성에 접근할 수
있습니다. SSH 터널이 더 안전하고 설정도 없습니다.

```bash
# 각자 로컬 PC에서
gcloud compute ssh <VM이름> --zone <존> -- -L 8000:localhost:8000
# 그다음 브라우저에서 http://localhost:8000
```

이 경우 `docker-compose.yml`의 포트를 `"127.0.0.1:8000:8000"`으로 바꿔 외부 노출 자체를
막아두면 더 확실합니다.

## 갱신 / 정지

```bash
git pull && docker compose up -d --build   # 코드 갱신 후 재배포
docker compose restart                      # 재시작만
docker compose down                         # 정지
```

전처리 캐시를 다시 만든 경우(`output/*.pkl` 교체)에는 컨테이너를 재시작해야 합니다 —
프로세스가 캐시를 메모리에 들고 있기 때문입니다.

## 리소스

CPU 전용으로 구성했습니다(`Dockerfile`에서 torch를 CPU 휠로 설치). 질문 하나당
임베딩은 짧아서 CPU로 충분하고, GPU를 쓰면 CUDA 베이스 이미지 + VM에
nvidia-container-toolkit 설정이 추가로 필요합니다.

- 메모리: 임베딩 모델을 올린 뒤 프로세스가 3~4GB 정도를 씁니다. VM 메모리가 8GB
  미만이면 여유를 확인하세요.
- 디스크: 이미지 약 3~4GB(torch/transformers 포함) + 모델 캐시 2.2GB.
- 문서별 임시 인덱스는 최근 16건까지만 들고 있다가 오래된 것부터 버립니다
  (`app/main.py`의 `_MAX_CACHED_INDEXES`).

## 문제가 생기면

| 증상 | 원인/해결 |
| --- | --- |
| `전처리 캐시가 없습니다` | `output/merged_docs.pkl`이 없음. step2를 돌려 만들고 `output/`에 넣으세요. |
| `No module named 'src.chunking'` | `chunks.pkl`이 예전 평면 구조(`src/chunking.py`) 시절에 만들어진 것. `app/main.py`에 옛 모듈 이름을 새 경로로 연결하는 호환 처리가 들어 있어 그대로 열립니다 — 그래도 이 오류가 보이면 그 호환 처리보다 먼저 unpickle이 일어난 경우이니 알려주세요. |
| `OPENAI_API_KEY가 잡히지 않았습니다` | 레포 루트 `.env`에 키를 넣고 `docker compose up -d`로 다시 띄우세요(컨테이너 재생성 필요 — `restart`만으로는 환경변수가 안 바뀝니다). |
| 자유 질문이 아주 느림 | 첫 호출의 모델 다운로드입니다. 위의 예열 명령으로 미리 받아두세요. |
| 답변 품질이 이상하게 낮음 | `/api/status`의 `embedding.name`을 확인하세요. `tfidf_hash_fallback`이면 모델 다운로드에 실패해 어휘 기반 폴백으로 돌고 있다는 뜻입니다(VM에서 HuggingFace로 나가는 네트워크 확인 필요). |
| 컨테이너가 계속 재시작 | `docker compose logs --tail=50 bidfit` 확인. 대개 볼륨 경로나 `output/` 권한 문제입니다. |

## API만 따로 쓰고 싶을 때

웹 UI 없이 API만 호출해도 됩니다(다른 프론트를 붙이거나 팀 다른 도구와 연동할 때).

```
GET  /api/health                     헬스체크
GET  /api/status                     코퍼스/모델/키/.env 상태
GET  /api/documents?q=검색어          문서 목록
GET  /api/quick-replies              버튼 11종 정의
GET  /api/models                     선택 가능한 생성 모델 목록
POST /api/quick-answer  {doc_id,key} 정규식 후보 (API 호출 없음)
POST /api/expand        {doc_id,key,index,width}  후보 주변 원문 더 보기 (API 호출 없음)
POST /api/ai-summary    {doc_id,key,model?}       후보 + parent chunk 기반 LLM 요약
POST /api/chat          {doc_id,question,model?}  문서 범위 RAG 답변 + 근거
```

`model`을 생략하면 `src/generation/generation.py`의 기본 모델(`gpt-5-mini`)을 씁니다.
`/api/ai-summary`와 `/api/chat` 응답에는 실제로 사용한 `model`과 `elapsed_ms`(생성에
걸린 시간)가 함께 담기므로, 모델별 속도 비교를 화면 밖에서도 그대로 수집할 수 있습니다.

## 생성 모델 목록 바꾸기

화면 상단 드롭다운 목록은 `BIDFIT_MODELS` 환경변수로 정합니다(쉼표 구분). 비워두면
`gpt-5-mini, gpt-5-nano`가 뜹니다 — 지금 팀 API 키로 부를 수 있는 게 이 둘뿐이라
기본값을 그렇게 잡았습니다. 목록에 없는 모델 이름이 요청으로 들어오면 400으로
거절하니(오타로 API 호출이 낭비되는 걸 막기 위함), 쓸 수 있는 모델이 늘면 여기에
추가해야 합니다.

```bash
echo "BIDFIT_MODELS=gpt-5-nano,gpt-5-mini" >> .env
docker compose up -d      # 환경변수는 컨테이너 재생성이 필요합니다(restart로는 안 바뀜)
```

`doc_id`가 한글·괄호·대괄호가 섞인 원본 파일명이라 URL 경로 대신 전부 POST 본문으로
받습니다.
