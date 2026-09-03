# EH-RC0 Evidence 작업 오류·수리

- 2026-09-03 17:46 KST: store TDD에서 아직 없는 모듈 ImportError 1건(red). 구현 후 타입/store 13 PASS.
- store patch의 __init__ import 문맥이 실제 absolute import와 달라 apply_patch 원자 적용 거부. 실제 파일을 확인해 문맥 수정 후 적용; 기존 파일 손상 없음.
- 읽기 전용 manifest 탐색에서 확장자를 `hwp`로 가정해 StopIteration. 실제 `.hwp`/`.pdf`를 확인해 재실행.
- 타입 리뷰 P3: 2**53 초과 정수 bbox의 float 변환 손실 발견. 원값 round-trip 검사와 회귀 추가.
- DTO/graph 검증은 외부 원본의 진실성 인증이 아니다. builder의 source artifact binding은 후속 leaf에서 검증한다.
- EH1.3 builder TDD missing module red→green, 17 tests PASS.
- EH1.4 구조 splitter 검증 1 FAIL: 공백 제거된 청크를 separator 없이 합쳐 `.split()`한 테스트가 단어를 합쳤다.
  구현 assertion을 느슨하게 하지 않고 미포함 원문 문자가 전부 공백인지, span 비중첩, 모든 비공백 원문 문자의 순서·동일성을 검증하도록 수정.
- 읽기 전용 리뷰가 multipart config 혼합/비공백 gap, splitter receipt 불일치, source section 충돌,
  private root symlink 이탈 4건을 재현했다. config·coverage·section binding, 실제 child ID 재구성,
  private symlink 거부를 추가했다. 리뷰어가 같은 4개 재현의 거부와 public escape 미발생을 확인했다.
- Kiwi 0.23.2에서 `num_workers=0` deprecation warning을 확인했다. 실제 단일 worker인 명시값 1로 고정하고
  identity/receipt도 1로 정정했다.
- 실제 MPS KURE 빌드는 1,048.18초, 9,496행으로 완료. 새 private artifact load/search와 기존 page
  control load/search가 모두 성공했고 source_unchanged=true였다. 이는 품질 비교가 아니라 실행 smoke다.
- Phase gate 리뷰 P1 3건: caller가 synthetic을 real로 표기 가능, restricted BM25가 scope 밖 DF/평균 길이를
  사용, raw DenseChildLane이 row binding 없이 생성 가능. production KureEmbeddingProvider의 비주입
  provenance에서만 real을 산출하고, scope population으로 통계를 재계산하며, 검증된 artifact loader만
  DenseChildLane을 만들도록 변경했다. 각 재현을 회귀로 추가했다.
- 첫 provenance patch가 같은 필드 문맥을 가진 HuggingFaceTokenCounter 생성자에 잘못 삽입되어 기존
  provider test 1건이 NameError로 실패했다. 해당 블록을 KureEmbeddingProvider 생성자로 이동하고
  provider focused 회귀를 재실행했다.
