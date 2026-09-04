# EH2.6.c2 semantic integrity review

- 날짜: 2026-09-05
- 범위: `execution_contracts.py` semantic verifier obligation/execution/receipt
- 상태: RESOLVED

## 증상

집중·관련 테스트는 통과했지만 독립 wiring 감사에서 c2 call graph가 사용하는 `SCHEMA_VERSION`,
`_require_hash`, `validate_harness_execution_config`, `unicodedata.normalize/category`의 재바인딩을 runtime
dependency gate가 모두 감지하지 못하는 틈을 찾았다. 또한 execution을 `completed`로 전환한 다음 receipt를
mint해, mint-time contract failure에서 receipt 없는 완료 이력이 남을 수 있었다.

후속 acceptance 리뷰에서는 source가 소멸한 뒤에도 local execution history가 계속 남는 수명 누수와,
factory-only로 계약한 private verifier request/evidence가 일반 dataclass 생성자를 열어 둔 불일치를 찾았다.
이를 재현하려던 첫 verifier fixture는 method가 외부 module global을 직접 참조해 synthetic runtime seal에서
`synthetic_component_state_not_sealable`로 거부됐다.
최종 수명 재리뷰에서는 constructor를 닫은 뒤에도 pickle/copy protocol이 token 없이 private DTO를 재구성하는
직렬화 우회를 추가로 확인했다.

## 원인

새 semantic 함수·DTO·registry pin은 추가했지만 그 함수가 간접 참조하는 기존 validator와 imported module
attribute까지 threat-model inventory를 확장하지 않았다. 완료 전환과 receipt mint 순서도 하나의 close
operation으로 검토하지 않았다. history는 receipt GC 생존만 고려하고 owner source 종료 시 cleanup과 object ID
재사용을 고려하지 않았으며, private 타입이라는 이름만으로 생성 경계가 닫힌 것으로 오해했다.

## 수리

- schema/type/validator/function/module attribute를 runtime pin에 추가했다.
- receipt mint/register 성공 뒤에만 `completed`로 전환하고, mint 실패는 sanitized contract error와 `failed`
  consumed history로 닫았다.
- schema 및 Unicode attribute rebinding이 provider 호출 전 차단되는 focused 회귀를 추가했다.
- source weak lifetime에 execution key를 묶어 receipt GC 동안에는 replay를 차단하고 source 종료 시 dual history를
  함께 정리한다.
- private request/evidence 생성자를 token factory-only로 닫았다.
- `__reduce__`/`__reduce_ex__`를 fail-closed로 고정하고 pickle/copy/deepcopy가 모두 거부되는 회귀와 class pin을
  추가했다.
- post-call drift fixture는 기존 sealed reentry module 패턴을 재사용하고 request 관찰은 외부 임시 파일에만 기록해
  verifier instance/class state를 바꾸지 않도록 했다.

## 검증

- focused normalizer+semantic: 26/26 PASS
- related retrieval/fusion/follow-up: 118/118 PASS
- full: 1,212/1,212 PASS
- repository safety: 846 files PASS
- 실제 API/model/Langfuse 호출: 0

## 예방

provider boundary leaf마다 direct symbol뿐 아니라 reachable constant, preflight validator, module attribute와
completion/receipt 원자성, owner 수명 종료 cleanup, private DTO 생성 경계를 별도 체크리스트로 감사한다.
