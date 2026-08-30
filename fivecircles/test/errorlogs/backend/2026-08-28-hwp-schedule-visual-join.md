Timestamp: 2026-08-28
Context: representative HWP schedule fill evidence join

Issue
- RenderTree의 병합 anchor와 canonical cell span이 달랐고 공유 테두리에 약 0.1px 좌표 차이가 있어
  실제 일정 fill이 있는 행을 누락했다.

Resolution
- 병합된 빈 fill anchor를 행 단위 evidence로 합치고, 일의적인 `M`/`M+n` header에만 연결했다.
- 공유 테두리 비교에는 0.5px 이하의 bounded tolerance를 적용하되 label/header 의미가 모호하면
  schedule fact를 만들지 않도록 fail-closed했다.

Prevention
- 시각 좌표 tolerance는 semantic header와 direct fill evidence가 모두 맞는 좁은 join에만 사용한다.
- 대표 일정표의 row-scoped fact와 unrelated-row 비간섭 회귀를 함께 유지한다.
