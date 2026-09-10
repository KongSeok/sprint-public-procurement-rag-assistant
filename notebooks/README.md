# notebooks/

Generation 파이프라인(문서 힌트 매칭 → 청크 선택 → 답변 생성 → 채점) 개발 과정에서
진행한 실험 노트북 모음이다.

시간순으로 정리했고, 각 파일 맨 위 셀에 더 자세한
목적·과정·결론 주석이 있으니 특정 실험을 깊게 보고 싶으면 해당 노트북을 직접 열어보면 된다.

모든 실험은 core40(40문항)·rag-56(56문항)·set-13(13문항) 골든셋 기준으로
검증했고, 변경 전후 점수를 비교해 실제로 개선됐는지 확인한 뒤에만 코드에 반영했다.

---

## 1. 검색 스택 선정

| 파일명 | 무엇을 확인하려 했나 | 무엇을 알아냈나 |
|---|---|---|
| `stack_experiment.ipynb` | 임베딩 모델(bge-m3 · KURE-v1 · Qwen3-Embedding)마다 정답 청크가 검색 순위 몇 등에 나오는지 비교 | 임베딩별로 특정 질문에서 순위 차이가 뚜렷하게 나는 것을 확인. 이 결과가 이후 KURE-v1 채택 근거가 됨 |
| `stack_experiment_2.ipynb` | 리랭커(bge-reranker) · BM25 · 하이브리드 검색을 추가하면 순수 벡터 검색으로 안 잡히던 실패 케이스가 개선되는지 | 단계별 순위 개선 폭을 측정. `bm25_hybrid_experiment.ipynb`·`faiss_chroma_experiment.ipynb`에서 확인한 "하이브리드 효과 미미함"이라는 결론과 이어짐 |
| `bm25_hybrid_experiment.ipynb` | KURE-v1 단독 벡터 검색에 BM25 키워드 검색을 결합하면 법률·계약 용어 중심 질문에서 검색 품질이 실제로 개선되는지 | 문서 힌트 매칭 + 법률 키워드 맵이 이미 어려운 케이스를 상당 부분 처리하고 있어 BM25 추가 효과가 크지 않음을 확인. 이후 순수 벡터 검색 + 규칙 기반 매칭 구조를 유지하기로 한 근거가 됨 |
| `faiss_chroma_experiment.ipynb` | 팀 재현성 검증에서 점수가 재실행마다 오르내리는 게 검색 엔진(FAISS/Chroma) 때문인지 | FAISS·Chroma 둘 다 완전히 결정론적임을 확인. 점수 변동의 원인은 검색이 아니라 LLM 생성 단계라는 근거를 마련 |

## 2. 파이프라인 최초 구축

| 파일명 | 무엇을 확인하려 했나 | 무엇을 알아냈나 |
|---|---|---|
| `pipeline_construction_and_visual_test.ipynb` | 문서 힌트 추출 + 법률 키워드 맵 + 표 보정을 결합한 답변 생성 파이프라인(`ask_rfp_final`)의 최초 완성본을 만들고, 조건 필터형·Visual(표/그림)·코퍼스 통계 질문에 어떻게 반응하는지 테스트 | 조건 필터형 질문은 잘 작동하지만 Visual 문항은 텍스트 파싱만으로 한계가 뚜렷함을 처음 확인. 코퍼스 통계 분석 결과(파일형식 비율, 예산 결측 현황 등)는 이후 채점 기준값으로 재사용됨 |
| `pipeline_scoring_and_grading_fix.ipynb` | `pipeline_construction_and_visual_test`에서 완성한 파이프라인을 core40 전체에 실행하고 자동 채점 함수를 만들어 정량 평가 | 초기 채점 함수(단순 문자열 포함 검사)의 한계로 정답인 답변이 오답 처리되는 사례 다수 발견. 날짜 표기 통일, 숫자 앞자리 0 허용, 기권 문구 확장, 단어 일치 임계값 완화(50%→40%)로 개선 — 이후 계속 이어지는 "규칙 기반 채점의 표현 차이 민감성" 문제를 처음 발견하고 대응한 실험 |

## 3. 문서 힌트 매칭 (질문에서 정답 문서를 찾는 로직)

| 파일명 | 무엇을 확인하려 했나 | 무엇을 알아냈나 |
|---|---|---|
| `rag56_first_run_and_doc_hint_fixes.ipynb` | rag-56을 처음 전체 채점했을 때 어떤 새로운 오탐이 나오는지 | "그랜드코리아레저(주)"처럼 별칭 딕셔너리 키와 실제 추출된 기관명의 괄호 표기가 어긋나 매칭이 통째로 실패하던 사례 등, 하나의 실패가 여러 원인이 겹친 경우를 다수 발견·해결 |
| `doc_hint_matching_experiment.ipynb` | "인천광역시" 질문에 "광주광역시 광주문화재단"이 잘못 잡히는 등 오탐 원인 | 행정구역 접미사("광역시" 등)가 블랙리스트에 없던 게 원인. 또한 같은 발주기관 내 여러 문서 중 하나를 고르는 4단계 로직이, 3단계에서 고친 키워드 체크를 4단계에서는 누락하고 있어 같은 오탐이 재발한다는 걸 확인 — 한 단어가 매칭 로직 여러 단계에 걸쳐 쓰인다는 핵심 교훈 |
| `doc_hint_matching_experiment_2.ipynb` | 블랙리스트 우회, 문서 1개뿐인 발주기관 오탐, 기권 답변 인식 누락 | substring이 블랙리스트 단어를 "포함한 채로" 더 길게 잘려 체크를 우회하는 패턴 발견·수정. "판정을 해드릴 수 없습니다"처럼 기권 문구 사이에 다른 단어가 끼어 매칭 실패하던 케이스도 발견해 ABSTAIN_PHRASES 보강 |
| `generation_prompt_and_variance_experiment.ipynb`의 후반부 | "운행기록" 같은 핵심 신호가 "용역은/사업은" 조사형 노이즈에 묻히는 문제 | stopwords 확장 + 조사 제거 후 매칭하는 v2 로직으로 개선. core40 영향 0건, 목표 문항만 정확히 개선됨을 확인 |

## 4. 프롬프트 발전 (v2 → v9)

| 파일명 | 무엇을 확인하려 했나 | 무엇을 알아냈나 |
|---|---|---|
| `generation_prompt_and_variance_experiment.ipynb` | 같은 질문을 다시 물으면 점수가 왜 달라지는지, 어떻게 줄일 수 있는지 | temperature 조정(모델 미지원으로 무효), reasoning_effort 상향(부분 개선), 다수결(5회는 안정적이나 비용 5배로 비실용) 순으로 시도 후, 결국 프롬프트 지시를 v3~v9까지 순차 추가하는 방향이 가장 효율적이라는 결론. v6(상충 정보 지시 전역 적용)은 오히려 변동성이 늘어 폐기하는 등 실패 사례도 그대로 기록 |

## 5. 인용 형식·목록형/랭킹형 질문 처리

| 파일명 | 무엇을 확인하려 했나 | 무엇을 알아냈나 |
|---|---|---|
| `citation_format_experiment.ipynb` | Citation Coverage가 채점기에서 0%로 나오는 이유, "학교 발주 사업" 같은 목록형 질문이 왜 다 안 찾아지는지 | 형식 불일치(실제 언급률 78.63%)가 원인이라 `[근거: 문서명]` 형식으로 통일해 해결. 목록형 질문은 벡터 검색으로는 k를 아무리 늘려도(80→200) 유사도 낮은 정답 문서를 놓친다는 걸 실증하고, 메타데이터 직접 필터링으로 전환해 해결 |
| `ranking_and_comparison_experiment.ipynb` | "예산이 가장 큰/작은" 질문 일반화, c19(6개 사업 동시 비교)가 왜 3개만 나오는지 | 검색 자체는 12개 문서를 다 찾고 있었는데 `doc_hints[:3]`이라는 상수 제한 때문에 컨텍스트에서 잘려나가고 있었음을 발견 → "다음 N개 사업" 감지 시 슬라이스를 동적으로 확장해 해결 |
| `prompt_phrasing_and_metric_extension_experiment.ipynb` | "합산하지 않는다" 같은 결론 표현 누락, "기간이 가장 긴/짧은" 질문 확장 | 그룹 설명을 문장형으로 유도하는 프롬프트 지시는 효과 없어 폐기. 대신 "합산 여부를 명확히 밝히라"는 지시는 개선 확인. 기간 기준 랭킹 처리 추가 중 두 사업의 기간이 동일한 동점 케이스를 발견해 max()/min() 로직의 동점 처리 버그를 예산·기간 양쪽에서 수정 |

## 6. 낮은 점수 문항 재조사

| 파일명 | 무엇을 확인하려 했나 | 무엇을 알아냈나 |
|---|---|---|
| `low_score_reanalysis_experiment.ipynb` | 낮은 점수 문항들이 검색 실패인지 생성 실패인지 채점 기준 문제인지 구분 | 7개 케이스 중 실제 검색·청크 선택 문제는 1개뿐이었고, 나머지는 생성 단계에서 우선순위가 밀리거나 채점 함수가 표현 차이를 엄격하게 판정한 경우였음. "여러 사업 중 조건에 맞는 걸 찾아 비교"하는 질문은 벡터 검색으로 원천적으로 불가능하다는 걸 확인하고, 메타데이터에서 직접 계산하는 별도 경로(g25) 신규 구현 |

## 7. 표기 정규화 및 규칙 기반 후처리 확장

| 파일명 | 무엇을 확인하려 했나 | 무엇을 알아냈나 |
|---|---|---|
| `keyword_completion_extension_experiment.ipynb` | 채점기 v3.1 재실행에서 드러난 재현성 문제(g16, h20)와 여전히 0점인 문항(g03/g04/g13/g25/visual-pdf-table-003), VLM 근거 ID 혼입이 우리 영역인지 | "100분의N"/"N점" 같은 표기가 LLM 생성마다 "N%"와 오가는 걸 확인해 정규화 함수 신규 구현. 트리거 키워드 리스트·`__FORCE__` 모드로 동의어 케이스까지 규칙 기반 후처리 확장. 표 구조가 파싱 과정에서 소실돼 "보완"이 안 통하는 경우 답변 자체를 교체하는 방식 도입. g04/g13/g25는 이미 정상 작동 확인(조장님 실행 시점 코드가 최신 미반영), VLM 근거 ID 문제는 우리 코드에 관련 로직이 전혀 없음을 확인해 VLM팀 소관으로 정리 |

---

## 읽는 순서

파이프라인이 지금 형태로 발전한 과정을 순서대로 따라가고 싶다면:

1. **검색 스택** — `stack_experiment.ipynb` → `stack_experiment_2.ipynb` → `bm25_hybrid_experiment.ipynb`
2. **파이프라인 최초 구축·채점** — `pipeline_construction_and_visual_test.ipynb` → `pipeline_scoring_and_grading_fix.ipynb`
3. **문서 힌트 매칭 최초 이슈** — `rag56_first_run_and_doc_hint_fixes.ipynb`
4. **프롬프트 v2~v9 발전** — `generation_prompt_and_variance_experiment.ipynb`
5. **변동성 원인이 검색이 아님을 확인** — `faiss_chroma_experiment.ipynb`
6. **문서 힌트 매칭 세부 수정** — `doc_hint_matching_experiment.ipynb` → `doc_hint_matching_experiment_2.ipynb`
7. **인용 형식 + 목록형 질문 처리** — `citation_format_experiment.ipynb`
8. **랭킹·다중비교 질문 확장** — `ranking_and_comparison_experiment.ipynb` → `prompt_phrasing_and_metric_extension_experiment.ipynb`
9. **낮은 점수 문항 마무리** — `low_score_reanalysis_experiment.ipynb`
10. **표기 정규화 및 규칙 확장 최종본** — `keyword_completion_extension_experiment.ipynb`

## 참고

- 실험 전체를 관통하는 서사와 최종 결론, 팀 채점기 이슈 공유 내용은 `docs/`
- 실제 프로덕션 코드는 `src/generation/answer_generation.py`, `src/generation/generation_prompts.py`
- 최종 평가 점수(core40/rag-56/set-13)는 `results/`