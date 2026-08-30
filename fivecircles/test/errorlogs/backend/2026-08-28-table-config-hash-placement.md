Timestamp: 2026-08-28
Context: page-v1 하위호환과 table-md-rowgroup-v1 config identity 검증

Issues
1) table prefix 정책 hash 항목이 실수로 `PageChunkConfig`에 들어가 기존 page-v1 config SHA를
   바꿨다.
2) 같은 항목이 실제 `TableChunkConfig`에는 빠져 있어 table artifact provenance가 반대로 약해졌다.

Resolution
- prefix 정책 항목을 page config에서 제거하고 table config로 옮겼다.
- page-v1 config SHA가 기존 고정값으로 복귀하고 refined page chunks 9,331개가 historical retained
  subset과 byte-level 동일함을 확인했다.
- runtime index gate가 실제 청크의 단일 config SHA와 metadata/index-config 선언을 모두 비교하도록
  보강했다.

Prevention
- 새 청킹 정책은 해당 lane의 config object에만 추가한다.
- 기존 lane의 고정 config SHA를 회귀 검사하고 runtime에서 선언 hash와 실제 chunk hash를 함께 묶는다.
