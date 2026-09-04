Timestamp: 2026-09-04 12:12 KST
Context: EH2.6.b1 BoundFact authority independent review

Issues
1) frozen request/planning/trace/store drift가 canonicalization 전에 악성 mapping·string 메서드를 호출할 수 있었다.

Resolution
- constructor-issued weak authority와 exact nested identity/type precheck를 공통 request/store 경계에 추가했다.
- fact bind/replay가 planner·mapping·hash 호출 전에 변조를 거부하도록 순서를 고정했다.

Prevention
- bomb mapping/string 호출 0회, equal clone, derived index drift, strict replay 회귀를 함께 유지한다.
