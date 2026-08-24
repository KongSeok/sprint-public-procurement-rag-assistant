# PDF Worker Pipe Deadlock

- Date: 2026-08-24 19:05 KST
- Stage: Private corpus integration test
- Failure: all 4 PDFs reached `pdf_extract_timeout` although their worker produced large text results.
- Root cause: the parent joined the worker before draining its Pipe, so large payloads blocked both processes.
- Fix: receive before join; added a 512 KiB synthetic PDF regression and retried all 4 PDFs successfully.
