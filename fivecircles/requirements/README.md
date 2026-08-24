# MidProjectRAG Requirements Space

이 폴더는 요구사항을 분석하고, 논쟁하고, 확정하는 공간입니다.

## 파일 역할

- `decisions.md`: 사용자가 확정했거나 근거 문서로 확정된 결정
- `current.md`: 현재 구현이 만족해야 하는 통합 요구사항
- `sources.md`: Notion/Drive의 역할, 접근 경계와 데이터 실사 사실
- `debates/`: 불명확·충돌·가정의 근거와 해결 상태

## 규칙

1. 충돌과 중요한 가정은 `debates/`에 근거·영향·임시 결정을 기록합니다.
2. 확정 결론은 `decisions.md`에 반영하고 `current.md`를 동기화합니다.
3. 제품 요구사항의 권위 순서는 이 파일이 아니라 `fivecircles/agent/authority.md` 한 곳에서 정의합니다.
4. 과거 프로젝트 자료는 `fivecircles/legacy/`에만 보존하며 현재 요구사항으로 인용하지 않습니다.
