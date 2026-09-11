# macOS 로컬 연결 점검 — 2026-09-11

## 범위와 계약

- develop 전용 `.venv`, localhost Ollama `qwen3:8b`, 팀 공유 청크 사본 사용.
- 기존 학습 환경·VM·원본 PKL은 변경하지 않는다. 데이터/모델/키 커밋 금지.
- 통합 앱에서 단독 프로토타입의 helper를 가져올 수 있도록 package import만 수정한다. 단독 실행 진입점도 유지한다.
- 공유 PKL의 이전 `src.chunking.Chunk`를 현재 클래스로 변환하되 본문/메타데이터/청크 ID는 보존한다. 변환 도구와 결과는 ignored artifacts/output에만 저장한다.
- merged_docs.pkl이 없으면 명시적으로 안내하고 중단한다. 청크를 이어 붙여 원문이라고 가장하지 않는다.
- Chroma 색인이나 병합 문서가 확보되기 전 전체 E2E 통과로 보고하지 않는다.

## 검증

1. `.venv/bin/python -m pytest tests/test_streamlit_compound_queries.py tests/test_generation_providers.py -q`.
2. 앱 import, 공유 98문서/18,239청크 로드 및 localhost 모델 실제 응답.
3. `streamlit run streamlit_demo/app.py`로 브라우저 기동; 준비되지 않은 자산은 정확한 오류 안내.
4. 실검색·생성·인용 검증은 데이터/색인 준비 후 별도 확인.

fivecircles 정책이 없는 develop이므로 로컬 실행 점검은 이 문서에 기록한다.

## 실행 결과

- PASS: 새 `.venv`에 requirements.txt + pytest 설치. 기존 환경 변경 없음. Python 3.12.14, Streamlit 1.63.0, Chroma 1.5.9, torch 2.14.0, sentence-transformers 6.0.1.
- PASS: 맥 MPS 가용; 기존 private/hf-cache의 KURE snapshot 1개 확인(모델 로드/새 임베딩은 하지 않음).
- PASS: localhost Ollama 조회 및 실제 앱의 `load_generation_client`로 qwen3:8b 호출. `max_completion_tokens=256, reasoning_effort=low`에서 content='OK', finish_reason='stop'. 외부 API/VM 호출 없음.
- PASS: 원본 98문서/18,239청크(parent 3,664 / child 14,572 / recursive 3)의 모든 필드를 변환 사본과 비교해 보존 확인. 원본 SHA256 `92187fcdabf350de7f3ff906a292d2ba1ecc9020862aaf1ad3c42f83def249cd`.
- PASS: 기존 관련 7개 + 신규 회귀 2개 = pytest 9 passed. PyMuPDF SWIG 경고 5개는 별도 비실패 경고.
- PASS: 브라우저에서 입찰메이트 제목, 실제 로컬 모델 태그, 두 기능 선택 및 missing merged 안내 확인.
- BLOCKED: merged_docs.pkl과 Chroma 색인을 찾지 못함. 전체 검색/생성/인용 E2E 및 원문 기반 빠른 검토는 미검증. merged가 확보되면 기존 Chroma 제공 또는 새 로컬 색인 생성이 필요.
- `.env`, `.venv`, output PKL, 변환 스크립트 artifacts의 gitignore 적용 확인. 커밋/푸시 없음.

### 발견·수정 이력

1. 최초 의존성 누락 → 격리 환경 설치로 해결.
2. 단독 스크립트 helper의 bare import → scripts package import로 수정, 실제 앱 import 통과.
3. 공유 PKL의 이전 클래스 모듈 경로 → 제한된 클래스만 허용하는 변환기로 새 output 생성, 원본 유지.
4. 초기 필드 동등성 검사의 NaN != NaN 때문에 AssertionError 발생 → 결측 NaN 쌍만 동등하게 처리해 모든 필드 재검증 통과. 제품 데이터 수정 없음.
5. Streamlit 소스 자동감시가 Transformers 선택 이미지 모듈을 탐색하며 torchvision 누락 경고를 다량 발생 → 아래 실행 명령의 자동감시 비활성화로 해소. 불필요한 비전 라이브러리 설치 없음.
6. 최초 짧은 Qwen 연결 검사(32 출력 토큰)는 reasoning만 반환 → non-thinking 옵션에서 OK 확인 후 앱과 같은 low 옵션/256 토큰으로도 OK 확인. 최초 빈 응답은 정상 응답으로 집계하지 않음.

### 재실행

워크트리 루트에서:

```sh
.venv/bin/python -m streamlit run streamlit_demo/app.py \
  --server.address 127.0.0.1 --server.port 18514 --server.headless true \
  --server.fileWatcherType none --browser.gatherUsageStats false
```

현재 점검 서버는 종료했다. 병합 문서 확보 전에는 화면에 누락 안내가 표시되는 것이 예상 결과다.

## 후속: 공유 병합 문서 연결 및 실제 RAG 검증

위 BLOCKED는 병합 문서를 받기 전의 기록이다. 이후 shared_team/merged_docs.pkl을 받아 다음과 같이 검증했다.

- 병합 문서 98건과 청크의 문서 ID 집합 일치. 원본과 사본 SHA256 일치: `44d40056bb6ba3f19b4904f19ac9e0e7f409419cdf349197885596a03fdd6e65`.
- 기존 공유 Chroma 색인은 없으므로 새 워크트리 output/chroma_db에 KURE로 최초 생성했다. 검색 대상 14,575개(child 14,572 + recursive 3), parent 3,664개는 문맥 확장용으로만 보존.
- 전체 저장 ID·본문이 검색 대상 청크와 정확히 일치. Chroma 컬렉션 `rfp_chunks__nlpai-lab_KURE-v1`, 차원 1,024. 무결성 결과: `artifacts/local-index-integrity.json`.
- 실제 브라우저 질문: “대한상공회의소 기업 재생에너지 지원센터 홈페이지 개편 사업의 계약기간과 용역비용을 근거와 함께 알려줘.”
- 응답: “계약기간은 계약체결일로부터 6개월 이내이며, 용역비용은 57,000,000원(VAT 포함)” + 해당 문서 ID 인용. UI 검색 근거 7개를 펼쳐 첫 원문에 두 값이 모두 있음을 확인. 처리 경로 통합 RAG 생성, qwen3:8b, UI 표시 52.4초. 단일 스모크의 소요 시간으로, 평균 지연/골든셋 점수가 아니다.
- 단일 문서 빠른 검토: 대한상공회의소 검색 → 1건 선택 → 예산/일정 버튼. 예산 57,000,000원과 일정 표시 통과. 시작일의 공개일 대체는 UI에서 추정값으로 명시됨.
- 문서명 없는문서_검증_739105 검색 → “검색 결과가 없습니다.” 표시 통과.
- 관련 회귀 9개 재통과. 전체 검색 결과/원문을 포함한 브라우저 스크린샷을 도구로 확인.
- 브라우저 자동화의 근거 expander role 이름 선택은 1회 실패했다. 실제 AX 요소를 재확인하여 펼침·원문 대조 성공. 앱 오류와 구분한다.
- VLM 캐시 0건: 시각 검색 미검증. 단일 문서 AI 요약·모든 질문 유형·131문항 성능평가 미실행.
- 흐름 보고서와 두 PNG는 `artifacts/local-rag-flow-validation.html` 및 인접 Mermaid/PNG에 저장. mmdc 렌더 성공, HTML 브라우저 열기는 파일 URL 정책으로 BLOCKED. 우회하지 않았으며 앱 localhost 실검증과 구분한다.
- 이 점검에서 시작한 Streamlit 프로세스만 재시작(10:54:54 KST). 다시 98문서/18,239청크 전체 검색 화면 진입, 최초 임베딩을 반복하지 않고 기존 색인 사용. 실행 장치 `mps:0`을 화면에서 확인.
- 최종 관련 회귀 9개 통과 및 git diff --check 통과. 앱은 `http://127.0.0.1:18514`에 켜둠. 모델·키·데이터는 ignored 경로에만 있고 커밋/푸시하지 않음.
- 최종 판정: 텍스트 RAG 실행 스모크 PASS_WITH_RISKS. 실제 질의 1건의 내용·문서 근거, 단일 문서 버튼 및 빈 검색 결과를 검증했으며 VLM·전체 질문 품질·보고서 브라우저 미리보기까지 통과했다는 뜻은 아님.

## 후속: VM 격리 배포 — 2026-09-11

- 사용자 승인으로 기존 팀 VM `rag-gpu-vm` / `sprint-ai-chunk5-01` / `us-central1-c`에 배포했다. 이전 절의 VM 미변경 계약은 로컬 점검 당시 범위이며, 이번에 별도 배포가 승인됐다.
- 기존 팀 저장소 HEAD는 `92120b3`, 로컬/원격 develop은 `e88eeb1`. 팀원의 수정된 노트북과 미추적 파일을 덮어쓰지 않도록 별도 `/home/kongseok/bidfit-develop-e88eeb1-20260911`에 배포했다.
- 배포 코드는 develop `e88eeb1` + 위 로컬 호환 패치다. 새 커밋 또는 origin push를 했다는 뜻이 아니다. 전송 tar SHA256: `4f39c32cede2c0c91a766a99911c2081f27b6edac22dfe86e4f1d32b0689196d`.
- 기존 VM의 venv와 서버 측 `.env`를 재사용한다. Mac의 Ollama/MPS 설정이나 개인 키를 전송하지 않았다. 기존 `BIDFIT_MODELS=gpt-5-mini` 유지. 현재 VM Qwen 8002/8003 서버는 확인되지 않았다.
- 데이터와 Chroma는 약 428MB 별도 사본이다. SQLite backup을 사용했으며 KURE 컬렉션 1,024차원, 98문서/18,239청크/검색 대상 14,575개의 전체 ID·본문 일치를 확인했다. 재임베딩하지 않는다. 기존 TF-IDF 컬렉션도 사본에 남아 있지만 앱의 검색 백엔드는 KURE를 명시한다.
- VM 데이터 receipt는 배포 폴더 `deployment-receipt.json`. 원본 PKL과 사본 해시 일치. 기존 VLM JSONL도 있을 경우 사본으로 연결했다.
- VM의 pytest 부재로 pytest 명령은 실패했다. 팀 환경에 설치하지 않고 기존 provider unittest 3개, compound 테스트 함수 4개, 동일 조건 runtime guard 검사 2개를 표준 라이브러리로 실행해 통과했다. 로컬의 pytest 9 passed 결과와 구분한다.
- 별도 transient systemd 서비스 `bidfit-streamlit-preview-20260911.service`, `127.0.0.1:8011`. SSH 종료 후에도 실행되지만 VM 재부팅 시 자동 복구되는 영구 서비스는 아니다. 외부 방화벽/공개 포트 변경 없음.
- 점검 중 기존 8010 프로세스가 사라지고 별도 GPU 프로세스가 생긴 것을 발견했다(기존 프로세스 종료 원인은 미확인). 이 작업에서는 기존 서비스 중지·재시작, 팀원 프로세스 종료를 하지 않았다.
- 브라우저 접속은 SSH 터널 `http://127.0.0.1:18516/` → VM 8011. 이 Mac에서 터널이 살아 있는 동안에만 접근할 수 있으며 공개 배포 URL이 아니다.
- 헬스체크 `ok`, 서비스 active/running 확인. 브라우저 데이터·검색 검증은 아래 후속 결과에 기록한다. 이번 검증의 유료 생성 호출은 하지 않는다.

### VM 운영 명령

```sh
sudo systemctl status bidfit-streamlit-preview-20260911.service
sudo journalctl -u bidfit-streamlit-preview-20260911.service -n 50 --no-pager
```

별도 배포만 중지하려면 위 정확한 서비스명으로 `sudo systemctl stop`을 사용한다. JupyterHub나 다른 앱 전체를 재시작하지 않는다.

### VM 브라우저 검증 결과

- PASS: 실제 VM 화면에서 문서 98개, 청크 18,239개, KURE-v1, 실행 장치 `cuda:0`, VLM 캐시 4건 표시. KURE GPU 메모리 약 2,372MiB. 동시 작업 프로세스 유지, 확인 시 시스템 가용 RAM 약 4.4GB.
- PASS: “3개월 이내의 사업 중 예산 10억 미만인 걸 모두 알려줘”를 전체 98문서 범위로 제출. 복합 조건 필터가 15개 사업을 반환했고 적용 조건은 90일 이내/10억원 미만으로 표시됐다. 실제 hybrid_search와 parent 문맥 확장도 실행됐으며 검색 근거 10개 표시, UI 단일 실행 1.3초.
- 이 질문은 복합 조건 필터 분기여서 `ask_rfp_v9`/OpenAI 생성 호출을 하지 않는다. 화면의 `openai/gpt-5-mini`는 선택된 모델 설정이지 이번 요청에서 모델을 호출했다는 뜻이 아니다.
- 초기 시작은 KURE 로딩과 BM25 재구성으로 수 분 걸렸다. 로그에서 기존 KURE 색인 재사용/재임베딩 생략을 확인했다. 시작 지연과 준비 후 검색 1.3초는 별도 측정이다.
- 결과 화면 스크린샷 육안 확인. 근거 expander의 Playwright role 선택은 일치 요소를 찾지 못해 실패했으며 앱 오류가 아니다. 이번 VM 점검에서는 펼친 근거 본문 대조는 미완료다.
- 최종: VM 별도 배포·CUDA·데이터 로드·실검색 스모크 통과. 일반 자유 질문의 유료 생성, VLM 품질, 전체 131문항 점수 및 공개 접속/영구 재부팅 자동시작은 검증·구현 범위 밖이다. 브라우저는 VM 연결 주소에 열어뒀다.
