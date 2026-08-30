Timestamp: 2026-08-28
Context: refined structured table Markdown chunk materialization

Issues
1) 첫 전수 생성에서 일부 긴 표 row가 `table_row_budget_exceeded`로 실패했다.
2) row를 vertical key/value로 나눠도 모든 part에 반복되는 문서 metadata prefix가 token 상한의
   상당 부분을 차지해 무손실 분할 공간이 부족했다.

Resolution
- 사업명·기관·locator는 필수로 두고 caption·parent·summary는 정해진 순서로만 추가하는 bounded
  prefix를 구현했다.
- prefix를 `min(200, max_tokens // 3)` 이하로 제한하고 이 정책을 table chunk config hash에
  포함했다.
- 원본 table cell text는 자르지 않고 oversized row만 deterministic vertical part로 분할했다.
- 전수 35,128개 청크를 다시 만들고 max 600 tokens, 초과 0개를 확인했다.

Prevention
- 반복 prefix와 본문을 하나의 최종 embedding text로 계산해 token/character 상한을 검사한다.
- table prefix 정책 변경은 반드시 table config hash와 oversized-row 회귀 테스트를 함께 바꾼다.
