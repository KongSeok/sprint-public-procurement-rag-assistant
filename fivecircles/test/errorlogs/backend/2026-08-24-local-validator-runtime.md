# Local Validator Runtime Limits

- Date: 2026-08-24 19:21 KST
- Stage: Test
- Failure: sandboxed `compileall` could not write caches; legacy macOS `tidy` rejected UTF-8 HTML5 markup.
- Fix: reran compile with project write permission and validated the HTML with an explicit UTF-8 tag-balance parser.
