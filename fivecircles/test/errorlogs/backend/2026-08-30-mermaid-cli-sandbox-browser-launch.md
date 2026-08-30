# Mermaid CLI sandbox browser launch failure

- Date: 2026-08-30
- Status: RESOLVED
- Impact: the flow-report source was valid, but the first diagram-rendering attempt could not produce the
  PNG verification artifact inside the restricted execution environment.

## Symptom

The Mermaid CLI reached its browser-launch phase and failed before rendering. The sanitized failure
evidence identified a browser sandbox/launch restriction; it did not identify a Mermaid syntax error or
expose document content.

## Root cause

The headless browser bundled with the CLI could not start under the default sandbox boundary. Diagram
generation depends on a browser process even when the input is a local Mermaid source file.

## Resolution

- Re-ran the same pinned Mermaid render through the approved local Chrome execution path.
- Kept the Mermaid source unchanged so the recovery did not mask a diagram-content defect.
- Produced the expected PNG and used it for the visual flow-report check.

## Verification

- The approved render completed successfully and created a non-empty PNG.
- The generated image was readable by the report pipeline.
- No private corpus path, filename, text, or credential was included in the command output or this log.

## Prevention

- Treat browser launch and Mermaid source validation as separate gates.
- Prefer the approved local Chrome renderer when the restricted environment rejects the headless browser.
- Never weaken browser sandbox settings or copy private input into logs as a rendering workaround.
