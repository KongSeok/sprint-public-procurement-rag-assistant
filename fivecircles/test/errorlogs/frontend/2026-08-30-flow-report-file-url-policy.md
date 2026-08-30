# Flow report local file browser policy block

- Date: 2026-08-30
- Status: ENVIRONMENT_BLOCKED / STATIC_QA_COMPLETE
- Impact: the closeout HTML could not be navigated in the in-app browser, so responsive behavior is not
  claimed as a live browser pass in this cycle.

## Symptom

Navigation to the local `file://` report was rejected by the browser URL security policy before page load.
No page script, image, or user data was executed or transmitted.

## Root cause

The in-app browser does not allow this local file URL. This is a browser execution boundary rather than an
HTML, Mermaid, or image-generation failure.

## Resolution and evidence

- Did not retry through localhost, another browser surface, raw browser commands, or a policy workaround.
- Rendered and visually inspected the current Mermaid PNG directly.
- Parsed the HTML structure locally: balanced tags, two existing PNG assets, two tables, eight headings,
  both responsive breakpoints, overflow wrapping, and no personal absolute path.

## Prevention

- Distinguish static artifact validation from live browser validation in closeout reports.
- Use an explicitly allowed preview surface in a future cycle when viewport screenshots are mandatory.
- Never convert a browser-policy block into a claimed visual PASS based only on static checks.
