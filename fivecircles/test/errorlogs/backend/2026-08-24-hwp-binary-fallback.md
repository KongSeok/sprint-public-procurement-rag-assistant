# HWP Primary Parser Fallback

- Date: 2026-08-24 19:16 KST
- Stage: Private corpus integration test
- Failure: 2 of 96 HWP files failed only in pyhwp's XML/text transform stage.
- Fix: added an isolated binary-model text fallback with distinct sanitized failure codes; both files recovered and the final 100-file verification passed.
