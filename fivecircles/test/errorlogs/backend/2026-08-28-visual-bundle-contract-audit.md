Timestamp: 2026-08-28
Context: independent P1 audit of HWP visual bundle

Issue
- 초기 단위는 table/image 산출물이 분리돼 통합 읽기 순서가 없었고 source/binary provenance,
  private-root containment, multi-file publish, strict image validation이 충분히 강제되지 않았다.

Resolution
- text/table/image ordered artifact를 추가하고 source와 rhwp binary를 실행 전·후와 publish 직전에
  hash 검증했다.
- 모든 출력·asset root의 private containment와 symlink를 확인하고 네 산출물을 stage한 뒤 metadata를
  마지막에 publish하며 hash 검증/rollback하도록 했다.
- asset manifest SHA/count/bytes/reference reconciliation, image header/dimension/pixel 상한,
  bbox/page containment와 duplicate-link 거부를 계약·스키마·회귀에 추가했다.

Prevention
- 여러 private evidence 파일은 metadata-last generation으로 게시하고 소비자는 metadata hash가 모두
  맞기 전 읽지 않는다.
- visual evidence producer와 JSON Schema의 required/provenance/geometry 조건을 같은 테스트에서 검증한다.
