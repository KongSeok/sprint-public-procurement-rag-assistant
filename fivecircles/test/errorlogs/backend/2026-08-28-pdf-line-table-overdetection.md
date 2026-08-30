Timestamp: 2026-08-28
Context: four-document pdfplumber visual PoC

Issue
- `lines` strategy가 일반 ruled table에는 유용했지만 조직도와 box diagram의 경계도 표 grid로 인식했다.
- 일정표에서는 제목·period header·direct fill rect를 찾았어도 일부 row label이 cell matrix에 정렬되지 않았다.

Resolution
- 상태를 `verified_table_structure`가 아닌 `line_table_candidate`와
  `image_geometry_candidate`로 낮추고 aggregate도 semantic object 수가 아님을 스키마에 고정했다.
- page bbox 밖 geometry는 fail-closed하고 네 PDF를 두 번 실행해 1,270 record byte determinism과
  strict schema를 확인했다.

Prevention
- PDF line detector count를 실제 표 수로 보고하지 않는다.
- diagram-heavy, ruled-table, schedule-table, borderless-table을 분리한 사람 fidelity gold 전에는
  PDF candidate를 canonical retrieval lane으로 활성화하지 않는다.
