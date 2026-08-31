# Visual crop blank regression in current working tree

작성일: 2026-08-31 10:30 KST
상태: **RESOLVED / VERIFIED**

## Symptom

당시 working tree 전체 discovery에서 visual crop·understanding 레인의 7개 테스트가
`visual_crop_blank` 오류로 종료됐다. 동시에 실제 대표 HWP bundle의 unique crop
14개가 모두 순백인데도 16개 placement가 eligible로 기록된 것을 확인했다. 이전 closeout의
green test와 대표 crop 완료 판정을 현재 증거에 그대로 적용할 수 없었다.

## Impact

- 본문 page Dense RAG와 refined 98 page index에는 영향이 없었다.
- visual crop을 그대로 사용하면 이미지 OCR·검색·citation에 무의미한 흰 근거가 들어갈 수 있었다.
- 새 blank gate가 과거 순백 test fixture도 정직하게 거부하면서 7개 회귀 오류가 드러났다.

## Current boundary

- 관측 오류 코드: `visual_crop_blank`
- 관측 범위: 실제 HWP representative crop과 visual crop/understanding tests
- artifact root cause: `@rhwp/core.renderPageSvg()`의 data-URI `<image>`를
  `@napi-rs/canvas.loadImage(Buffer(svg))`가 그리지 않았지만 PNG 구조/hash/dimension 검사만으로
  page render와 crop을 재사용했다.
- fidelity gap: nested SVG `viewBox`, ancestor rect clip, RGB linear component-transfer와 scalar
  opacity가 overlay 경로에 없었다.
- test root cause: 성공 fixture가 완전 흰 page를 정상 evidence로 사용했다.

## Required resolution

1. SVG data image를 bounded decode하고 MIME/magic을 대조한 뒤 base render 위에 합성했다.
2. root/nested `viewBox`, preserve-aspect-ratio, viewport·rect clip과 대표본의 linear RGB
   component-transfer/opacity를 source crop 및 bounded pixel effect로 반영했다.
3. renderer/config identity를 변경해 과거 bundle 재사용을 거부하고, 순백 crop은
   `visual_crop_blank`로 fail closed했다.
4. TIFF/GIF/WMF/SVG 등 현 renderer 미지원 source는 crop 없이 provenance-only quarantine으로
   유지했다.
5. `<style>` element, `class`, ancestor `display`/`visibility`/inline `style`과 `<defs>` 내부 image는
   지원하는 척 누락하지 않고 명시적 helper 오류로 fail closed했다.
6. 성공 fixture는 nonblank 픽셀을 포함하도록 고쳤고 blank/effect/structure 거부 전용 회귀를 추가했다.
7. 과거 순백 bundle은 삭제하지 않고 incident archive로 격리한 뒤 새 bundle을 canonical 경로로
   교체했다.

## Verification

- 대표 HWP 5/5, occurrence 27: eligible 15, TIFF quarantined 1, withheld 11
- unique crop 15/15 nonblank, nonwhite ratio 0.218264~1.0
- page render 14/14 nonblank
- helper SHA-256 `0b7ab8edd3b3cb6018704b40e1c7b662041a79c857dc99eba66432280cfc0a9b`
- artifact set `visualv2_1a25cd3f5f6c34dfe2e8ff9c`의 helper/object/occurrence hash reconciliation과
  expected identity strict reuse 통과
- 외부 API 호출 0회, `private_egress=false`
- 대표 5문서 530페이지의 `<style>`/`class`/`display`/`visibility`/`<defs>`-image 패턴 0건
- representative effect crop과 Chrome SVG 기준 비교: channel mean absolute error 0.754/255,
  RMSE 1.471/255
- 관련 helper focused test 11/11 통과
- repository-wide discovery 505/505, focused schema 2/2, compileall, Node syntax,
  `git diff --check`, repository safety 562 files 통과

## Prevention

- 과거 closeout의 통과 수치를 현재 working tree 상태로 재사용하지 않는다.
- 공유 보고서에는 현재 재실행 결과와 optional lane 실패 범위를 함께 적는다.
- 유효한 PNG hash와 dimension은 의미 있는 visual evidence의 충분조건이 아니다. 알파 합성 후
  nonblank pixel gate와 실제 표본 시각 검토를 함께 둔다.
- SVG image를 분리 합성할 때는 data URI뿐 아니라 viewBox, clip, filter/opacity와 paint-order
  위험을 계약에 열거하고, 지원하지 않는 effect는 실패시킨다.
- 실제 문서에 관측되지 않았다는 사실은 parser 허용 근거가 아니다. 대표 page scan과 별개로
  `<style>`/class/display/visibility/defs-image adversarial fixture를 유지한다.
