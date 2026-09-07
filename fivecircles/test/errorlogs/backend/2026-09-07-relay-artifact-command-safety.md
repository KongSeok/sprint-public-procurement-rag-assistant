# Relay 산출물 명령 오류 — 2026-09-07

## 범위

EH2.6.c4.2.b.2 사후 통합 확인과 다음 Design의 읽기 전용 계약 해시 계산. 제품 회귀 실패가 아니다.

## 증상·원인·조치

| 확인 단계 | 오류 | 조치 / 근거 |
| --- | --- | --- |
| 메인 staged 40파일 hash 재확인 | Node 기본 child-process buffer보다 report PNG가 커서 ENOBUFS, exit1 | maxBuffer 32 MiB를 명시한 재확인 exit0. 40개 hash·목록·branch/base·resources·whitespace 모두 일치. commit 8db0510 및 사후 영수증에 기록. |
| Astra Design 계약 초안 hash 계산 | Design이 보고한 shell quoting 오류: double-quoted payload의 백틱이 명령 치환되어 잘못된 입력 hash 발생 | Design은 첫 값을 폐기하고 single-quoted payload로 재계산했다고 보고했다. 메인이 설치한 실제 계약 bytes를 다시 해시해 일치 확인하기 전 사용하지 않는다. 제품/테스트/Git 변경 없음은 Design 보고이며 아직 원시 출력은 별도 보존되지 않았다. |

## 재발 방지

- 이미지 등 큰 바이너리는 내용 크기에 맞춘 buffer 또는 streaming hash를 사용한다. 실패를 내용 불일치로 분류하지 않는다.
- Markdown/코드가 든 명령 payload를 shell double quotes에 끼우지 않는다. apply_patch로 스크립트를 만들고 인자로 실행한다.
- 계약 ID는 설치된 파일의 실제 UTF-8 bytes로 다시 계산한다. 오류 계산값은 지시/후보의 권위로 삼지 않는다.
- 이 기록은 외부 실행·모델 호출·보안 검사 우회·제품 테스트 면제를 승인하지 않는다.

## 결과

메인 ENOBUFS 재확인은 해결 완료. 다음 계약은 설치된 실제 14,864 UTF-8 bytes를 메인이 독립 해시해 Design의 최종 계약 ID와 일치함을 확인했다. 폐기된 계산값은 사용하지 않았으며, 확인 후 post-fusion-directive-1을 Coder에게 전달했다.
