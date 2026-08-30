# PDF visual artifact predates recovery code and has no durable corpus runner

작성일: 2026-08-30
상태: **OPEN / REMEDIATION_PLANNED**

## Symptom

현재 private PDF visual PoC metadata와 record는 2026-08-28 16:47:46에 생성됐고,
`src/midprojectrag/ingest/pdf_visual.py`는 같은 날 20:22:38에 수정됐다. 따라서 현재 저장된
1,270개 candidate artifact는 현 코드의 전수 실행 결과가 아니다.

민감 본문을 출력하지 않은 구조 감사에서 다음 두 일정표 record의 첫 열 본문 라벨이 모두
`null`임을 확인했다.

- page 12, 30x11 table: 본문 29행, first-column nonempty 0
- page 8, 15x15 table: 본문 14행, first-column nonempty 0

현 unit test는 schedule geometry 복구 matrix를 persisted content에 넣는 경로를 포함해 28/28
통과하지만, 이 수정 뒤 PDF 4건 artifact를 다시 만들지 않았다.

## Additional evidence gap

- 427개 image-geometry candidate에는 bytes, xref, resource name, intrinsic size가 없다.
- read-only pypdf inventory는 page image resource entry 416개와 decoded-byte digest 92개를 찾았다.
  resource 재사용과 placement occurrence가 달라 427 bbox와 exact reconciliation이 필요하다.
- image candidate 70/427은 table bbox 안에 90% 이상 포함돼 `table child image` 계층이 필요하다.
- 현재 `.venv`에는 optional `pdfplumber`가 설치돼 있지 않다.
- PDF visual corpus를 다시 만드는 durable CLI/runner가 없다.

## Impact

- 843 table, 427 image 수치는 과거 geometry candidate 재고로만 사용한다.
- 현재 코드가 실제 PDF 4건의 row label을 복구한다고 주장할 수 없다.
- image OCR/caption을 지금 붙이면 actual PDF object 및 placement provenance에 묶이지 않는다.
- 재실행 명령이 없어 artifact freshness와 코드/config 재현성을 검증할 수 없다.

## Root cause

PoC가 one-off materialization으로 생성된 뒤 schedule recovery 코드가 보강됐지만, aggregate
artifact metadata에 adapter/code identity와 freshness gate가 없고 corpus runner도 제품화되지 않았다.
또한 `pdfplumber.page.images` geometry와 실제 PDF XObject/resource를 별도 계약으로 분리하지 않았다.

## Required resolution

1. PDF visual corpus용 durable CLI/runner와 synthetic CLI test를 추가한다.
2. metadata에 source manifest hash, parser/config hash, adapter/code identity, dependency version을 묶는다.
3. pypdf image/resource bytes와 pdfplumber placement bbox를 reconciliation한다.
4. vector diagram, table, table-child image, decorative, ambiguous 상태를 분리한다.
5. current code와 pinned `pdfplumber`로 4건을 새 v2 root에 재생성한다.
6. 두 일정표의 row label, 427 bbox reconciliation, stale-artifact refusal을 private gate로 검증한다.
7. v2가 통과하기 전 기존 artifact를 verified retrieval이나 OCR/caption 입력으로 승격하지 않는다.

PyMuPDF는 유용한 spike 후보지만 AGPL/상용 이중 라이선스이므로 별도 라이선스 결정 전 production
dependency에 넣지 않는다.

## Prevention

- Derived corpus metadata must bind the executable adapter and config used to create it.
- A code-newer-than-artifact observation is a review trigger; strict validation must use identity hashes,
  not mtime alone.
- PoC artifact generation must have a durable, tested runner before it becomes a rollout dependency.

## Verification performed

- metadata/code mtime comparison
- two schedule record shape/null-count audit without printing source text
- current optional dependency check: `pdfplumber_installed=False`
- `tests.ingest.test_pdf_visual`: 28/28 passed in the current project runtime
