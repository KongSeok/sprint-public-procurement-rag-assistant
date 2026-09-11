# VM 생성기 선택 계약 — 2026-09-11

## 목표·현재 상태

VM Streamlit의 드롭다운에서 GPT-5 mini / Qwen3.5-9B를 선택한다. 현재 develop의 KURE·Chroma·BM25·부모 문맥 확장은 그대로 둔다. 별도 EH 서버의 `/ask`는 전체 검색 실행이므로 생성기 대신 호출하지 않는다.

## 범위·가정

- 기존 Qwen 서버 원본과 code-v9/모델/어댑터/골든셋은 수정하지 않는다. wrapper 진입점에서 기존 Application/HTTP handler를 재사용한다.
- 같은 프로세스의 모델 1개와 EH 실행 잠금을 공유한다. 일반 생성에서는 학습 정책 어댑터를 끈 context를 사용하고 종료 시 복원한다.
- 사용자가 유휴 상태 확인 후 Qwen 서버 1회 재시작을 승인했다. 활성 요청이 있으면 중단하지 않는다. 모델을 중복 로드하거나 다른 GPU 프로세스를 종료하지 않는다.
- 공개 배포·전체 평가·검색 알고리즘 개선은 제외한다. 이번 실제 생성 스모크는 소수 문항이며 성능평가로 해석하지 않는다.

## API·오류 계약

- 기존 `/ask`, `/catalog`, `/health` 유지. `/health`에 생성 capability 정보만 추가.
- `GET /v1/models`: 지원 모델 `Qwen/Qwen3.5-9B`.
- `POST /v1/chat/completions`: JSON, model 고정, messages는 system/user/assistant의 비어 있지 않은 문자열 목록. non-streaming, tools/image/JSON-schema 미지원. 최대 본문 256KiB, 32 messages, 출력 1..1024 토큰, 전체 문맥 예산 16384 토큰. 초과 입력은 자르지 않고 거부.
- 응답은 Chat Completions의 choices[0].message.content/finish_reason, usage. 원문 프롬프트·키는 서비스 로그에 기록하지 않는다. 이 경로는 EH 평가/학습 trajectory에 섞지 않는다(api-outcome-evidence:v1).
- 준비 중 503, 잠금 점유 409, 잘못된 요청/문맥 초과 400, 추론 timeout 504. 빈 답변은 오류. 출력 잘림은 client에서 오류로 표시. 자동 OpenAI fallback·자동 재시도 없음.
- loopback-only 바인딩, 브라우저 Origin 요청 거부. 기존 `/ask` 입력 계약은 변경하지 않는다.

## 앱 계약

- VM 서비스 환경에서 `BIDFIT_MODELS=openai:gpt-5-mini,qwen3.5-9b:Qwen/Qwen3.5-9B`, `BIDFIT_QWEN35_9B_URL=http://127.0.0.1:18631/v1` 사용. 원본 공유 `.env` 변경 없음.
- OpenAI client는 그대로 유지. Qwen은 로컬 chat API와 Responses→chat 변환을 제공해 AI 요약도 같은 선택을 따른다. 모델별 출력 한도/실행 위치를 화면에 표시한다.
- 모델을 바꾸면 기존 대화/요약 결과를 초기화해 이전 모델 결과와 혼동하지 않는다. 검색 resource는 재사용한다.

## 완료 기준·배치

1. 생성 전용 API + client adapter 구현, fake backend/HTTP 검사 통과.
2. 드롭다운·세 경로 연결 및 기존 회귀 통과. 원본 보존·rollback 명령 확보.
3. 유휴 승인 게이트 후 wrapper 기동, `/health`/기존 catalog 보존, GPU 중복 로딩 없음 확인.
4. 브라우저에서 두 옵션 선택 및 Qwen 실제 생성 확인. mini는 작은 연결 스모크 1회로 확인하고 대규모/반복 유료 호출 금지. 결과/오류/한계 기록.

## 검증

단위: 모델 바인딩, Responses 변환, 토큰 제한, 빈값/잘림 오류, busy/ready/validation, 잠금 해제, 기존 API 전달. 서비스: HTTP 응답 형태, localhost/Origin 제한. 실제 VM: readiness·모델 목록·짧은 추론·Streamlit 질문/전환. 검색 색인과 기존 EH 모델/스냅샷을 변경하지 않았는지 확인한다.

## 미해결·인계

초기 계획 시 구현/배포 미완료. 긴 문맥이 16384 토큰을 넘으면 명시적 오류이며 임의 절단하지 않는다. 기존 EH 대화의 메모리 내 상태는 재시작으로 초기화되고 기존 저장 결과는 보존한다. 아래 실행 결과에서 실제 완료 여부를 갱신한다.

## 실행 기록

- 사용자 유휴 재시작 승인 수신. 재시작 직전 ready/busy=false, PID 27462의 정확한 실행 명령과 원본 SHA256을 확인했다.
- 원본 서버 SHA256 `f6302709ab13efc3119e840e7ec3746bfdc46cc408fb5c6533640409c83abf17` 유지. 별도 wrapper 위치 `/home/pio/evo35-cuda-test-20260910/apps/shared-generation-20260911-01/streamlit_demo/shared_qwen_server.py`.
- 새 unit `bidfit-qwen-shared-20260911.service`, same port 18631, separate private session output. 기존 EH 모델/코드/학습 snapshot은 재사용하며 수정하지 않는다.
- 패키지 SHA256 `99d1d4695e6782029c602bd39d68bc47d8d056dac146156038cafe2ccee7df0c`.
- 로컬 `pytest tests/test_local_generator_switch.py tests/test_streamlit_runtime_prerequisites.py tests/test_generation_providers.py tests/test_streamlit_compound_queries.py -q -p no:cacheprovider`: 34 passed, 기존 SWIG deprecation 경고 5개. 네트워크 생성은 fake backend로 검증했으며 실제 모델 통과와 구분한다.
- 별도 단위검사로 base-model 생성 중 정책 어댑터 OFF/종료 후 복원, 긴 입력의 GPU 실행 전 차단, shared lock/busy 처리, 원래 /ask 라우팅 보존, 모델 선택 변경 시 답변만 초기화됨을 확인했다.

### 복구

현재 shared unit을 유휴 상태에서만 중지한 뒤 기존 진입점을 다시 실행하면 이전 EH 서버로 돌아간다. 실행 환경은 기존 `.venv/bin/python`, `PYTHONPATH=/home/pio/evo35-cuda-test-20260910/code-v9/src`, 원본 `apps/hotline-streamlit-20260911/server.py`, 기존 output `data/private/streamlit-sessions/20260911-020821`이다. 동시에 두 모델 서버를 시작하지 않는다.

Streamlit 복구는 배포 폴더의 `streamlit_demo/app.py.before-generator-switch-20260911` 사본과 `/run/systemd/system/bidfit-streamlit-preview-20260911.service.d/generator.conf` 전환 설정을 대상으로 한다. 공유 원본 `.env`나 기존 팀 레포 전체를 되돌리는 방식이 아니다.

## 최종 실행 결과

- 배포 앱 unit에 두 `BIDFIT_MODELS` 값과 localhost Qwen URL만 추가했다. 공유 `.env`는 수정하지 않았다. 원래 app.py는 지정한 backup 파일로 보존했다. 커밋/푸시는 하지 않았다.
- 배포 도구 최초 앱 단계는 다른 사용자 소유 폴더의 backup.exists() 권한 오류로 파일 변경 전 실패했다. 기존 승인 sudo로 존재 여부를 확인하도록 도구만 수정하고 재실행 성공했다. 완료 전 “적용했다”는 중간 안내는 즉시 정정했다.
- Qwen wrapper ready: 98문서, 9,496 text chunks, 836 visual chunks, adapter_step=108, code-v9. 이 수치는 EH의 코퍼스이고 Streamlit의 18,239청크/검색 대상 14,575개와 섞지 않는다. /health, /v1/models 정상. 기존 server.py SHA256 일치.
- 실제 합성 연결 호출: mini는 `gpt-5-mini-2025-08-07`로 “확인”, stop, 3.02초. Qwen은 `Qwen/Qwen3.5-9B`로 “확인”, stop, 1.35초. 각 1회이며 유료 mini 호출은 이 한 번뿐이다. 모델 성능 비교 수치가 아니다.
- 브라우저에서 두 모델 드롭다운 확인 → Qwen 선택 → 98문서/18,239청크/cuda:0 그대로 유지. 실제 질문 “대한상공회의소 기업 재생에너지 지원센터 홈페이지 개편 사업의 계약기간과 용역비용을 근거와 함께 한 문장으로 알려줘.” 실행.
- Qwen 결과: 계약체결일부터 6개월 이내 / 57,000,000원 VAT 포함 / 정확한 해당 문서 ID 인용. UI 경로 qwen3.5-9b/Qwen/Qwen3.5-9B, 통합 RAG 생성, 13.8초, 검색 근거 6개. 앞선 원문 점검의 두 사실과 일치한다. 스크린샷 육안 확인. 검색 근거 expander 내부 재검수나 131문항 평가를 했다는 뜻은 아니다.
- Qwen → mini → Qwen을 실제 조작해 설명/선택값 전환과 이전 모델 답변 초기화를 확인했다. 검색 인덱스 로딩은 반복되지 않았다.
- 단일 문서 빠른 검토 → 대한상공회의소 → 사업목적 요약 → AI 요약 버튼도 로컬 client의 Responses→chat 변환으로 실제 응답했다. 결과는 “제공된 문서에서 확인할 수 없습니다.”였다. 전달/생성 경로는 통과했으나 목적 질문의 정답성은 미통과/미확정이며 후보 문맥 선정·생성 품질은 별도 검토다.
- 실행 시 GPU 프로세스는 공유 Qwen 서버와 Streamlit KURE 2개다. Qwen 모델을 선택할 때마다 추가 로딩하지 않는다. 기존 공유 서버의 /ask 실제 전체 재평가는 실행하지 않았고, 원본 파일·API forwarding·모델 metadata 보존과 동등 단위검사로 확인했다.
- Mermaid 목표/현재 PNG 및 HTML은 `artifacts/generator-switch-*`로 기록했다. HTML browser preview는 파일 URL 보안 정책으로 차단돼 우회하지 않았다. 앱 localhost의 실제 화면/전환/답변은 별도 검증했다.
- 최종 판정: 생성기 전환 구현·VM 배포·실제 호출 스모크 통과(품질/긴 문맥/전체 평가 별도). 서비스는 transient unit이므로 VM 재부팅 뒤 영구 자동 재기동까지 구현한 것은 아니다.
