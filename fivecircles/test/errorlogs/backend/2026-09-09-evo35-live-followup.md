# EVO35.2 live follow-up failure and rejected repairs

- Recorded: 2026-09-09T14:12:12+09:00; actual run receipts are private.
- Original comparison and fixed reference succeeded; original Korean follow-up failed at2 invalid actions with0 search/read/answer.
- Model used historical citation IDs as current evidence. CandidateA added explicit current-ID lists/instructions but failed again. CandidateB removed machine-only historical IDs from the policy projection; model then used a document ID as evidence and emitted invalid JSON.
- Both99-test candidate regressions passed. Live failure remained, so neither candidate was adopted; source and extra test changes were archived privately and removed from the active tree. Restored212 tests PASS, exit0, skip0.
- No evidence/scope/JSON guard was weakened and no answer was fabricated. The source changes did not prove a live-policy fix; maintain REPLAN instead of retrying indefinitely.
- First RED:4 tests, failures1/errors3. Projection RED:4 tests, failures2. The first patch application was rejected until minimal-hunk syntax was supplied; no partial source patch occurred.
- Grouped read-only tool inspection failed once; ordinary narrower reads later succeeded without altered permissions. This was separate from model inference results.
- refs: ../../../work/2026-09-09-evo35-live-report.md. Raw logs, rejected diffs and per-run hashes: resources/data_refined/private/diagnostics/evo35-live-20260909-001/ (Git excluded).
