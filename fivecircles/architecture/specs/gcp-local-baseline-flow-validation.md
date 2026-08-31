# GCP Local Mini131 Baseline Flow Validation

검증일: 2026-09-01
범위: refined98 page-only, KURE, exact dense retrieval, Mac Ollama Qwen equivalent, GCP Qwen3-8B-AWQ/vLLM target, Mini131 전체 자산

현재 closeout은 **RAG 129/129 + parser 2/2, lane-complete 결정론 receipt, fresh Sol semantic
aggregate 완료**를 뜻한다. Named human gold 승인과 live GCP telemetry는 아직 닫히지 않았으므로
`mac_local_equivalent`, `official=false`, `passed=false`, provisional 경계를 유지한다.

## Target Flow

![Target GCP local Mini131 baseline](gcp-local-baseline-target-flow.png)

Target source: [`gcp-local-baseline-target-flow.mmd`](gcp-local-baseline-target-flow.mmd).
목표는 129 RAG를 lane별로 실행하고 parser 2건을 별도 ETL 결과로 유지한 뒤, content-free
결정론 receipt와 hash-bound blind semantic aggregate를 각각 닫는 것이다. 공식 비교는 live
L4/vLLM/FAISS telemetry가 있는 `gcp_local` record만 허용한다.

## Current Implementation Flow

![Current local Mini131 implementation](gcp-local-baseline-current-flow.png)

Current source: [`gcp-local-baseline-current-flow.mmd`](gcp-local-baseline-current-flow.mmd).
Aggregate semantic evidence: [content-free public semantic receipt](../../../evaluation/baselines/gcp-local-kure-qwen3-8b-awq-mini131-v1/mac-local-equivalent-semantic-receipt.json).

현재 `candidate_output_visible_to_reviewer=false`는 raw candidate artifact·파일 경로·case ID·lineage를
reviewer에게 직접 노출하지 않는다는 뜻이다. frozen rubric 적용에 필요한 answer/status, 대화 문맥,
retrieved/cited evidence는 sanctioned hash-bound blind projection으로 전달된다.

## Target vs Current Gap

| ID | Node/edge | Status | Implementation evidence | Remaining gate |
| --- | --- | --- | --- | --- |
| G1 | refined98 → pinned KURE cache/exact index | **MATCHED — measured** | 98 documents, 9,331 chunks and 1,024-d normalized vectors are hash-validated on the Mac path | reproduce with FAISS CPU on the L4 host |
| G2 | frozen Mini131 inventory → complete candidate coverage | **MATCHED — measured** | all 129 RAG rows closed; outcomes are 87 answered, 36 abstained and 6 retained errors | none for candidate coverage |
| G3 | answer/set/visual/analytics lane adapters | **MATCHED — executed** | page-answer 96, set 13, visual 10 and analytics 10 all reached terminal candidate states | none for candidate execution |
| G4 | parser C21/C22 → separate ETL result | **MATCHED — measured** | current pinned parser reran both cases at 2/2 PASS; parser is excluded from the RAG semantic mean | none for parser coverage |
| G5 | private transcript → deterministic diagnostics | **MATCHED — measured** | Recall@1/5/10 `0.921986/0.987589/0.991135`, MRR@10 `1.0`; candidate errors remain in denominators | do not substitute diagnostics for semantic judgment |
| G6 | deterministic diagnostics → lane-complete public receipt | **MATCHED — remediated** | metric coverage is complete: set count accuracy `0.538462`; visual document/page Recall@10 `1.0/0.6`, object `0`; analytics 10/10 and 139/139 comparisons pass | map preflight is 5,094 tokens; the 102,687-token worst-case final probe is a non-readiness stress case rejected before transport |
| G7 | raw candidate → sanctioned blind projection | **MATCHED — contract/adapter** | raw artifact identity and lineage stay hidden while required answer/status/chat/evidence are hash-bound into the blind packet | none for projection contract |
| G8 | blind projection → fresh Sol semantic aggregate | **MATCHED — measured** | primary 129, secondary 4, adjudicator 3; accepted 88, rejected 41, acceptance `0.682171`, mean `70.135659` | do not reuse prior API judgments or treat this as gold approval |
| G9 | semantic aggregate + named human gold → gold-approved closeout | **BLOCKED** | semantic ledger is complete but gold remains draft | obtain named human gold approval |
| G10 | loopback vLLM → live L4 telemetry | **BLOCKED** | adapter/run-record guards exist; the Mac Ollama/NumPy run is not L4/vLLM/FAISS evidence | explicit VM authorization, live run, `gpu_seconds` and `peak_vram_gb` |
| G11 | official GCP result → API↔GCP comparison | **BLOCKED** | comparison correctly rejects `mac_local_equivalent` evidence | valid same-hash `gcp_local` records with complete telemetry |

## Done / Not Done Priority

Scoring: upstream 0–4 + connection 0–3 + safety 0–2 + validation 0–2 + risk -3–0.

| Rank | Work unit | Score | State | Next action |
| ---: | --- | ---: | --- | --- |
| 1 | Mini131 candidate + parser execution | 10 | **DONE — measured** | preserve immutable private transcript and 6 measured errors |
| 2 | Lane-complete deterministic scorer/receipt | 9 | **DONE — measured** | preserve complete metric coverage and fail-closed global-set preflight evidence |
| 3 | Fresh Sol semantic aggregate | 8 | **DONE — measured** | preserve exact role counts, workflow validation and content-free aggregate |
| 4 | Named human gold approval | 7 | **BLOCKED — external review** | record approval independently from the candidate/Sol ledger |
| 5 | Live Qwen3-8B-AWQ/vLLM on L4 | 7 | **BLOCKED — external execution** | start the VM only with explicit authorization; collect complete telemetry |
| 6 | API↔GCP controlled comparison | 6 | **BLOCKED — depends on rank 5** | compare only same-hash official GCP records |

## Scoring Criteria

- Upstream and connection value reward paths that unlock complete evaluation and comparable evidence.
- Security value rewards loopback transport, raw-artifact isolation, hash-bound blind projection,
  content-free receipts and false-label prevention.
- Validation value rewards deterministic contract/schema tests and render/readback evidence.
- Risk penalizes paid/live VM execution, large downloads and human-only review gates.

## Color Semantics

- Green: implemented and validated normal control path.
- Blue: selected external/cloud projected model path.
- Amber: private, local-first, blind-review or explicitly non-official evidence path.
- Red: blocked, restricted, unsupported, fail-closed or active gap path.
- Gray: branch, helper or exact-control input.

## Validation Evidence

- Frozen coverage readback: 129/129 RAG terminal candidates and live parser C21/C22 2/2 PASS.
- Public aggregate boundary: question, answer, source text, case ID and rationale remain absent from
  the content-free receipt and this report.
- Release-audit gaps and their fail-closed resolutions are recorded without private content in
  `2026-09-01-mini131-release-audit-metric-coverage.md` and
  `2026-09-01-mini131-semantic-adjudication-workflow.md` under the backend error-log directory.
- Mermaid target/current source is rendered with `mmdc 11.15.0`, transparent background and scale 2.
- Static HTML QA requires two non-empty images, five valid local artifact links, five legend items,
  11 gap rows, six priority rows and the provisional closeout boundary.
- Browser render QA stores screenshot evidence under `fivecircles/test/playwright-screenshots/` and
  must show both diagrams plus the gap and priority tables.
- Closeout verdict: **131/131 COVERAGE, LANE-COMPLETE RECEIPT AND FRESH SOL AGGREGATE MATCHED /
  HUMAN GOLD AND LIVE GCP EVIDENCE NOT CLOSED**.
