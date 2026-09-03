# 입찰메이트 (BidFit)

> 공공입찰 컨설턴트를 위한 근거 기반 RFP 의사결정 코파일럿

Repository: `sprint-public-procurement-rag-assistant`

입찰메이트는 공공입찰 컨설턴트가 고객사에 적합한 제안요청서(RFP)를 찾고, 참가 조건과 위험 요소를 원문 근거와 함께 검토하도록 돕는 RAG(Retrieval-Augmented Generation) 서비스입니다.

단순한 문서 질의응답을 넘어 `RFP 탐색 → 핵심 조건 확인 → 위험 검토 → 문서 비교 → 컨설팅 브리프 작성`으로 이어지는 실제 업무 흐름을 지원하는 것을 목표로 합니다.

## 1. 문제 정의

입찰 컨설턴트는 다음 작업을 수작업으로 반복해야 합니다.

- 많은 공고 중 고객사와 관련된 RFP 탐색
- 수십~수백 페이지 문서에서 핵심 조건 추출
- 참가 자격, 공동수급 조건, 필수 제출서류 확인
- 지체상금, 하자보수, 손해배상 등 위험 조항 탐지
- 여러 RFP 비교 및 고객사 전달용 검토자료 작성

문서가 많고 길어질수록 검토 시간이 증가하고 중요한 조건을 놓칠 위험도 커집니다. 입찰메이트는 제공받은 약 100개의 RFP와 메타데이터를 검색하고, 검색된 원문만을 근거로 답변하여 검토 시간을 줄입니다.

## 2. 핵심 사용자 흐름

```text
고객사 조건 또는 자연어 질문 입력
    → 적합한 RFP 후보 탐색
    → 사업 개요와 핵심 조건 요약
    → 참가 자격 및 위험 조항 검토
    → 후속 질문과 원문 근거 확인
    → 여러 RFP 비교
    → 컨설팅 브리프 및 체크리스트 생성
    → 입찰 참여 여부 의사결정 지원
```

## 3. 핵심 기능

| 기능 | 설명 |
| --- | --- |
| RFP 탐색 | 사업 분야, 금액, 마감일, 발주기관, 지역 등 자연어 조건으로 보유 RFP 검색 |
| 입찰 검토 카드 | 사업 개요, 참가 자격, 제출서류, 평가 방식, 위험 요소를 정형 형식으로 제공 |
| 근거 기반 Q&A | 답변과 함께 문서명, 페이지, 근거 문장을 제시 |
| 멀티턴 대화 | 선택한 RFP, 고객사 조건, 이전 질문의 맥락을 유지 |
| 리스크 조항 탐지 | 지체상금, 하자보수, 손해배상, 계약해지, 재위탁 제한 등 검토 필요 조항 제시 |
| 다중 문서 비교 | 여러 RFP를 동일 기준으로 비교하고 각 값의 문서 근거를 표시 |
| 고객사 기반 매칭 | 적합, 검토 필요, 부적합 가능성, 판단 불가의 설명 가능한 단계로 판정 |
| 컨설팅 브리프 | 고객 미팅에 활용할 수 있는 1페이지 검토 요약 생성 |

법률적 입찰 가능 여부를 확정하지 않으며, 확인이 필요한 조항과 원문 근거를 제공하는 도구로 범위를 제한합니다.

## 4. MVP 범위

### 필수 구현

- PDF/HWP 텍스트, 표, 페이지 정보, 메타데이터 추출
- 문서 정제, 청킹, 임베딩 및 벡터 DB 저장
- 등록된 RFP 대상 자연어 검색
- 단일 RFP 기반 질의응답
- 문서명, 페이지, 근거 문장 표시
- 이전 질문을 기억하는 후속 질문
- 원문에 없는 질문에 대한 기권 처리
- Golden Set 기반 검색 및 답변 평가

### 확장 후보

- 30초 입찰 검토 카드
- 기본적인 다중 문서 비교
- 고객사 프로필 기반 추천 및 매칭
- 리스크 조항 자동 탐지
- 검색 결과 재정렬(Reranking)
- 근거 위치 하이라이트 및 답변 신뢰도 표시
- API 모델과 GCP 로컬 모델 비교

### 제외 범위

- 나라장터 실시간 크롤링과 신규 공고 알림
- 법률적 입찰 가능 여부 확정
- 실제 입찰서 자동 제출
- 복잡한 운영 스케줄링 인프라

## 5. RAG 파이프라인

```text
PDF/HWP + 메타데이터
    → 텍스트·표·페이지 정보 추출
    → 정제 및 문서 구조 기반 청킹
    → 임베딩 생성 및 벡터 DB 저장
    → 사용자 질문 분석
    → 메타데이터 필터 + 문서 검색
    → Dense / BM25 / Hybrid Retrieval
    → 필요 시 Reranking
    → 질문 유형별 답변 생성
    → 답변 + 문서명 + 페이지 + 근거 문장
```

### 답변 생성 원칙

- Retrieval이 제공한 컨텍스트만 사용합니다.
- 문서에서 확인되지 않은 사실은 생성하지 않습니다.
- 사실과 해석을 분리합니다.
- 수치, 일정, 자격 조건에는 출처를 표시합니다.
- 불확실한 내용은 `확인되지 않음` 또는 `추가 확인 필요`로 답변합니다.

## 6. 모델 실행 시나리오

| 구분 | 시나리오 B: API 베이스라인 | 시나리오 A: GCP 로컬 모델 |
| --- | --- | --- |
| 목적 | 우선 구현 및 기준 성능 확보 | B안 완성 후 비교 실험 |
| 생성 모델 | OpenAI API 후보 모델 비교 | Qwen, Llama, Gemma 계열 후보 비교 |
| 임베딩 | `text-embedding-3-small` 후보 | 실험 결과에 따라 선정 |
| 벡터 저장소 | FAISS 또는 Chroma | FAISS 또는 Chroma |
| 주요 평가 | 정확도, 속도, 질문당 비용 | 한국어 품질, 근거 충실성, 속도, GPU 메모리 |

최종 모델은 선호가 아니라 동일한 Golden Set에서 측정한 정확도, 속도, 비용을 기준으로 선택합니다.

## 7. 평가 계획

Golden Set에는 기본 사실, 참가 자격, 표 정보, 위험 조항, 문서 비교, 후속 질문, 답변 불가 유형을 고르게 포함합니다.

| 구분 | 평가 항목 |
| --- | --- |
| Retrieval | Recall@k, 정답 문서 Top-3 성공률, 정답 페이지·청크 검색률, 필터 정확도 |
| Generation | 답변 정확성, 근거 충실성, 환각 여부, 페이지 인용 정확도, 기권 정확도 |
| 운영 | 응답 시간, 질문당 API 비용, GPU 메모리, 모델별 추론 속도 |
| 업무 효과 | 핵심 필드 추출 정확도, 수작업 검토 대비 절약 시간 |

## 8. 기술 스택

초기 베이스라인 기준이며 실험 결과에 따라 변경될 수 있습니다.

| 구분 | 기술 |
| --- | --- |
| Language | Python |
| Document Processing | PyMuPDF, HWP parser, pandas |
| Embedding | OpenAI Embedding 또는 Hugging Face Embedding |
| Retrieval | FAISS/Chroma, Dense, BM25, Hybrid Retrieval |
| Generation | OpenAI API, Hugging Face Transformers |
| Demo UI | Streamlit |
| Infrastructure | GCP VM, NVIDIA L4, JupyterHub |

## 9. 프로젝트 구조

```text
.
├── app/                  # 데모 애플리케이션
├── configs/              # 모델 및 실험 설정
├── data/                 # 로컬 데이터, Git 업로드 금지
├── docs/                 # 기획서, 보고서, 회의 기록
├── notebooks/            # 데이터 탐색 및 실험 노트북
├── results/              # 공개 가능한 평가 결과
├── src/
│   ├── data_processing/  # 문서 추출, 정제, 청킹
│   ├── retrieval/        # 임베딩, 인덱싱, 검색
│   ├── generation/       # 프롬프트 및 답변 생성
│   └── evaluation/       # 검색·생성 성능 평가
└── tests/                # 테스트 코드
```

실제 디렉터리는 구현을 진행하면서 생성합니다.

> `feat/rag-pipeline-and-eval`에서 위 구조에 없던 `scripts/`를 추가로 만들었습니다 — 재사용
> 가능한 CLI 실행 스크립트(파이프라인 단계 실행, 평가/비교 실험 실행)라 `notebooks/`(ipynb 탐색용)
> 규칙과는 맞지 않아서 임시로 최상위에 뒀습니다. 팀 구조에 맞게 이름/위치를 바꿀지는 리뷰 때 논의 부탁드립니다.

## 10. Git 협업 규칙

### 언어 및 이름 규칙

- 코드 식별자, 파일명, 폴더명, 브랜치명은 **영어**를 사용합니다.
- README, 문서, PR 설명, 커밋 요약은 **한국어**를 사용합니다.
- Python 파일과 폴더는 `snake_case`를 사용합니다.
- 브랜치는 `<type>/<kebab-case-description>` 형식을 사용합니다.
- 경로에는 공백, 한글, 특수문자를 사용하지 않습니다.
- 노트북은 `YYYYMMDD_topic_owner.ipynb` 형식으로 작성합니다.

예시:

```text
src/data_processing/hwp_parser.py
notebooks/20260825_chunking_baseline_kongseok.ipynb
feat/retrieval-baseline
fix/hwp-page-mapping
experiment/chunk-size
```

### 브랜치 규칙

| 브랜치 | 용도 |
| --- | --- |
| `main` | 리뷰와 검증이 끝난 통합 코드 |
| `feat/*` | 새로운 기능 구현 |
| `fix/*` | 오류 수정 |
| `experiment/*` | 모델, 청킹, 임베딩, 검색 비교 실험 |
| `docs/*` | README, 보고서, 문서 수정 |
| `chore/*` | 설정, 의존성, 폴더 구조 등 유지보수 |

`main`에는 직접 push하지 않고 작업 브랜치에서 Pull Request를 생성합니다.

```bash
git switch main
git pull origin main
git switch -c feat/retrieval-baseline
```

### 커밋 메시지 규칙

형식은 `<type>: <한국어 요약>`으로 통일합니다. 타입은 소문자, 콜론 뒤에는 공백 한 칸을 사용하고 문장 끝에 마침표를 붙이지 않습니다.

| 타입 | 사용 시점 | 예시 |
| --- | --- | --- |
| `feat` | 새로운 기능 추가 | `feat: BM25 검색 기능 추가` |
| `fix` | 버그 또는 잘못된 동작 수정 | `fix: HWP 페이지 번호 매핑 오류 수정` |
| `update` | 데이터, 설정, 모델 후보, 기존 내용 갱신 | `update: 임베딩 모델 비교 결과 갱신` |
| `experiment` | 실험 코드나 결과 추가 | `experiment: 청크 크기별 Recall@5 비교` |
| `refactor` | 기능 변화 없는 코드 구조 개선 | `refactor: 검색 파이프라인 모듈 분리` |
| `perf` | 속도 또는 메모리 성능 개선 | `perf: 임베딩 배치 처리 속도 개선` |
| `test` | 테스트 추가 또는 수정 | `test: 답변 기권 케이스 추가` |
| `docs` | README, 주석, 보고서 수정 | `docs: 실행 방법과 협업 규칙 추가` |
| `style` | 포맷팅, 공백, 이름 등 비기능 수정 | `style: ruff 기준으로 코드 포맷 정리` |
| `chore` | 패키지, 설정, 기타 유지보수 | `chore: 개발 의존성 파일 추가` |
| `build` | 빌드 또는 패키징 설정 변경 | `build: Docker 이미지 설정 추가` |
| `ci` | 자동화 워크플로 변경 | `ci: pull request 테스트 추가` |
| `revert` | 이전 변경 되돌리기 | `revert: 하이브리드 검색 적용 취소` |

`feat`는 feature의 약어이며 `fit`이 아닙니다. `update`는 범위가 넓으므로 가능하면 `feat`, `fix`, `docs`, `refactor`처럼 목적이 명확한 타입을 먼저 사용합니다.

### 커밋 및 Pull Request 원칙

- 하나의 커밋에는 하나의 논리적 변경만 포함합니다.
- 하나의 Pull Request에는 하나의 목적만 포함합니다.
- PR 제목도 커밋과 같은 형식을 사용합니다.
- PR 본문에는 작업 내용, 확인 방법, 실험 결과, 관련 이슈를 기록합니다.
- 모델·청킹·검색 실험은 설정값과 평가 지표를 함께 남깁니다.
- 병합 전 최소 한 명의 팀원에게 리뷰를 요청합니다.

```bash
git add <변경한-파일>
git commit -m "feat: 검색 결과에 페이지 근거 추가"
git push -u origin feat/retrieval-baseline
```

### 버전 태그 규칙

Git은 커밋마다 `0.0.1`을 자동으로 붙이지 않습니다. 팀에서 의미 있는 통합 시점에 직접 태그를 생성합니다.

| 버전 | 기준 예시 |
| --- | --- |
| `v0.1.0` | API 기반 공통 베이스라인 완성 |
| `v0.2.0` | 검색 고도화 및 평가 반영 |
| `v0.3.0` | GCP 로컬 모델 비교안 완성 |
| `v1.0.0` | 최종 발표 및 제출 버전 |

## 11. 보안 및 데이터 관리

- 원본 RFP와 외부 공유가 제한된 데이터는 GitHub에 업로드하지 않습니다.
- API Key와 비밀번호는 `.env`에 저장하고 커밋하지 않습니다.
- `.env.example`에는 변수 이름만 기록하고 실제 값은 작성하지 않습니다.
- 벡터 인덱스와 임베딩에는 원문이 포함될 수 있으므로 공개 여부를 확인합니다.
- 모델 가중치, 캐시, 대용량 결과물은 Git이 아닌 별도 저장소를 사용합니다.
- 공개 가능한 코드, 평가 결과, 2차 가공 자료만 저장소에서 공유합니다.

커밋 전 반드시 확인합니다.

```bash
git status
git diff --staged
```

## 12. 역할 분담

| 담당 | 팀원 | 주요 업무 |
| --- | --- | --- |
| PM·통합 | TODO | 일정 관리, 요구사항 정리, 통합, 발표자료 |
| 데이터·청킹 | TODO | 문서 추출, 정제, 메타데이터 연결, 청킹 실험 |
| Retrieval | TODO | 임베딩, 벡터 DB, 검색, 필터링, 검색 평가 |
| Generation·UI | TODO | 프롬프트, 답변 생성, 출처 표시, 데모 UI |

## 13. 진행 상태

- [x] GitHub 저장소 생성
- [x] GCP VM 및 JupyterHub 환경 구축
- [x] 프로젝트 기획 및 MVP 범위 정리
- [x] README와 Git 협업 규칙 작성
- [x] 팀원 역할 확정
- [x] 데이터 구조 분석 및 전처리 (`feat/rag-pipeline-and-eval`, `src/data_processing`)
- [x] 공통 RAG 베이스라인 구현 (`feat/rag-pipeline-and-eval`, `src/retrieval` + `src/generation`,
      시나리오 B: API 임베딩 비교 + KURE-v1/BM25 hybrid + gpt-5-mini)
- [x] Golden Set 구축 (`feat/rag-pipeline-and-eval`, 공식 111건 + golden-set-v3-share 공유 lane 연동)
- [x] 검색 및 생성 성능 개선 실험 (`feat/rag-pipeline-and-eval`, Parent-Child·임베딩 A/B·리랭커·
      가중치 튜닝·프롬프트 개선 — 상세는 `docs/rag-pipeline-and-eval-summary.md`)
- [ ] API 모델과 GCP 로컬 모델 비교 (시나리오 A는 아직 미착수)
- [ ] 데모 및 최종 보고서 완성
