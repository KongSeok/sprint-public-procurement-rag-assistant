# c1 deleted pin helper test fixture

- 발생: 결합 변조 회귀 테스트가 이미 module namespace에서 삭제된 `_e1_callable_pin`을 호출해 `AttributeError`로 실패했다.
- 원인: production private helper의 초기화 이후 수명을 테스트가 잘못 가정했다.
- 수정: 테스트 전용 `_callable_pin`이 공개 동작을 호출하지 않고 동일 tuple shape를 독립 구성한다.
- 방지: 삭제되는 production private helper를 테스트 fixture 의존성으로 사용하지 않는다.
