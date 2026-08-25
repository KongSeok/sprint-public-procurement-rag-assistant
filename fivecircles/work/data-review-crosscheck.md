# Teammate Data Review Cross-check

날짜: 2026-08-25

## 목적

팀원이 사전 탐색한 데이터 리뷰를 실제 manifest, 원문 추출 결과와 교차확인한다. 정확한
Notion 주소와 원문 파일명은 Git 밖 private 참조에만 둔다.

## 확인 결과

| 리뷰 항목 | 교차확인 | 판정 |
| --- | --- | --- |
| corpus 100건, HWP 96·PDF 4 | manifest 및 원문 inventory 동일 | 일치 |
| CSV 파일명과 원문 파일명 0건 일치 | `Copy of ` 1회 제거와 Unicode NFC 정규화 전에는 불일치, 적용 후 100/100 exact join | 원인·해결 일치 |
| CSV `텍스트`가 원문보다 잘림 | preview는 80~18,328자이며 검색 본문에서 제외됨 | 일치 |
| PDF 4건 preview가 심하게 짧음 | 원문 재추출은 45,855·117,337·120,299·208,445자 | 일치, 최대 문서 추가 QA |
| HWP 1건 preview가 비정상적으로 짧음 | 최단 preview 80자 사례가 `rhwp` 페이지 본문 59,901자·86쪽으로 복구됨 | 일치 |
| HWP 전체 재파싱 필요 | `rhwp v0.8.4` 페이지 텍스트와 표 구조 96/96 성공 | 완료 |
| 사업 금액 결측 | 1건 | 일치, 수동 보정 보류 |
| 공고번호·차수 결측 | 각각 18건 | 일치 |
| 입찰 시작일 결측 | 26건 | 일치 |
| 입찰 마감일 결측 | 8건 | 일치 |

PDF 재추출 문자 수는 팀원 PyMuPDF 결과와 짧은 세 문서에서 약 1% 이내다. 가장 긴 문서는
팀원 결과 232,359자 대비 현재 `pypdf` 결과 208,445자로 약 10% 짧으므로 표·읽기 순서와 함께
원인 확인이 필요하다.

## 결정

- CSV `텍스트`는 preview/hash 비교에만 쓰고 retrieval evidence로 사용하지 않는다.
- HWP/HWPX는 `rhwp` 직접 파싱을 주 경로로 사용한다.
- naive 임베딩은 page text `primary` block만 사용한다. 구조화 table block은
  `structured_auxiliary`로 보존하고 별도 retrieval 실험 전까지 중복 투입하지 않는다.
- `hwp5txt`와 pyhwp binary-model은 `rhwp` 실패 시에만 fallback으로 유지한다.
- 결측 metadata는 원본 CSV를 직접 수정하지 않는다. 확인 가능한 값도 별도 provenance를 가진
  correction overlay로 만들지 여부를 팀이 결정한 뒤 반영한다.
- HWP를 PDF로 일괄 변환하지 않는다. SVG/한컴 PDF는 page/bbox 시각 검증 안전망으로 사용한다.

## 남은 검증

- HWP 5건: 논리 표와 render-tree bbox 조인율, 병합·중첩표, 한컴 페이지 정합
- PDF 4건: 표 헤더 반복 노이즈, 표·bbox, 가장 긴 문서의 약 10% 문자 수 차이
- 임베딩·인덱스 생성 후: 누락 문서·빈 청크·metadata 불일치를 이 리뷰와 다시 교차확인
