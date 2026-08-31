# Mini131 live provider recovery

- Date: 2026-08-31
- Stage: gpt-5-mini integrated provisional baseline
- Scope: content-free operational incident record

## Issues

1. Core40에서 provider 요청 이후 `APIConnectionError`가 발생한 2건이 있었다.
2. Gap30의 첫 조건목록 요청 1건은 OpenAI Structured Outputs가 지원하지 않는
   `uniqueItems` 때문에 HTTP 400으로 거절됐다.

## Resolution

- 세 provider 시도와 원래 `error` 상태를 private transcript에 그대로 보존했다.
- 고정 기준선의 no-retry 계약에 따라 실패 문항을 다시 호출하지 않았다.
- 연결 상태가 불확실한 Core 2건은 검증된 문항별 최대 비용을 reserve하고 public receipt에
  content-free runtime amendment와 감사 hash를 남겼다.
- 이후 Gap set 요청에서는 `uniqueItems`를 제거하고 선택 문서 ID의 유일성은 application
  validation으로 검사했다. 오류 문항의 답은 재생성하지 않았다.

## Prevention

- OpenAI 지원 Schema subset을 provider 첫 호출 전에 합성·live smoke로 확인한다.
- provider 시도 후 실패는 실행 전 실패와 구분하고, exact transcript·비용 reservation·재시도
  횟수를 함께 봉인한다.
- 기준선 중간의 계약 수정은 source/target runtime hash와 영향을 받은 문항 수를 공개 영수증에
  기록하되 질문·답변·본문은 노출하지 않는다.

## Pass evidence

- Core 40/40, Gap 30/30, Visual/EDA 20/20 완료.
- provider retries 0, 전체 후보 비용 USD 0.21345322, 비용 상한 미초과.
- Mini131 preflight 129/129, 전체 unittest 728/728 PASS.
