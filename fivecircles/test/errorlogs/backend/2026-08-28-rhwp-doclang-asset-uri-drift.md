Timestamp: 2026-08-28
Context: rhwp DocLang image asset reconciliation

Issue
- DocLang XML의 image URI와 실제 export된 cell image filename이 항상 byte-equal하지 않아 정상 그림을
  missing asset으로 처리할 수 있었다.

Resolution
- exact relative path를 우선 사용하고, coordinate URI는 pinned rhwp OTSL의 `fcel`/`ched` ancestry와
  `block`/`ldiv` 구조가 실제 emitted filename을 정확히 재구성할 때만 허용한다.
- broad unique-prefix와 terminal-picture-ordinal fallback은 구조 증명 없이 잘못 연결할 수 있어
  제거했다. merge/row continuation token은 active cell state를 초기화한다.
- PNG/JPEG/BMP/TIFF magic, 구조, dimensions, byte/pixel 상한과 content hash를 다시 검증했다.
- 17개 문제 문서의 143 picture와 전체 94 HWP의 452 picture를 구조적으로 감사해 unresolved,
  duplicate, inventory mismatch가 모두 0임을 확인했다.

Prevention
- parser가 제공한 asset URI를 실제 파일 존재 증명 없이 신뢰하지 않는다.
- 경로 reconciliation은 exact path 또는 exact OTSL structural reconstruction만 허용한다.
- parser 버전·writer grammar가 바뀌면 새 token/location fixture를 먼저 추가하고 전체 구조 감사를
  다시 통과하기 전 resolver grammar를 넓히지 않는다.
