Timestamp: 2026-08-31 20:00
Context: Mac-equivalent golden runner P1 hardening smoke

Issues
1) load_mac_pipeline이 generation_counter를 참조했지만 초기화는 build_mac_semantic_index에 잘못 삽입되어 첫 재실행이 NameError로 종료됐다.

Resolution
- PinnedQwenChatTokenCounter import와 초기화를 load_mac_pipeline 안으로 이동하고 2문항 실주행을 재검증했다.

Prevention
- 서로 다른 factory 함수에 같은 지역변수를 추가할 때 targeted integration smoke와 정의-사용 rg 검사를 함께 실행한다.
