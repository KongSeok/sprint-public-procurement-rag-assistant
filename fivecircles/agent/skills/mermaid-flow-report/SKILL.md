---
name: mermaid-flow-report
description: Create workflow validation reports with Mermaid target/current diagrams, generated PNG images, an HTML comparison page, color semantics, gap tables, priority scoring, and Playwright render verification. Use when validating agent flows, provider/privacy routing, API selection, wrapper dispatch, RAG/GraphDB, state machines, or when the user asks for Mermaid PNG/HTML reports. Trigger also when the user says "report", "보고해", or "스킬보고해".
---

# Mermaid Flow Report

## Philosopher / Coder relay mode

Apply this section only when the user or active flow form selected
`philosopher-coder`; standalone/solo behavior is unchanged.
Resolve `fivecircles/agent/skills/collaboration/SKILL.md` from the verified
project root first, otherwise use the installed sibling collaboration skill.
Read that entrypoint and its `references/relay-cycle.md` before this phase.
That reference owns collaborative role routing, closeout order, and re-entry;
the ordinary lifecycle below applies outside this mode. Higher-priority
instructions, project authority, required validation, and user scope still win.
If the dependency is unavailable, report the gap; do not silently run solo.

Use the last closeout report as the next opening input when its code, contract,
evaluation and environment fingerprint still matches. Record the reused artifact
and fingerprint; regenerate affected diagrams/PNG/HTML when it changes. Mandatory
delivery-boundary visual checks remain required. Do not rerender unchanged images
or run the whole suite merely because a leaf TODO ended. Report protocol alignment
separately from demonstrated live runtime behavior.

Use this skill when a workflow must be proven visually and not just described in prose.

## Output Contract

Produce or update these artifacts whenever practical:

1. `*.md` report with:
   - target Mermaid flow
   - current Mermaid flow
   - target vs current gap table
   - done/not-done priority table
   - scoring criteria
   - validation evidence
2. `*-target-flow.mmd` and `*-current-flow.mmd` source files.
3. PNGs generated from the `.mmd` files with global `mmdc`.
4. HTML report that embeds the PNGs with clickable links to `.mmd` and `.png`.
5. Screenshot evidence from Playwright/browser render.

For AlphaFlower Admin AI provider/privacy flow, prefer:

- `fivecircles/architecture/spec/AIConsolLayers/provider-policy-flow-validation.md`
- `fivecircles/architecture/spec/AIConsolLayers/provider-policy-flow-validation.html`
- `fivecircles/architecture/spec/AIConsolLayers/provider-policy-target-flow.mmd`
- `fivecircles/architecture/spec/AIConsolLayers/provider-policy-current-flow.mmd`

Path convention:

- Paths above are repository-root relative paths.
- When this skill is mirrored globally under `~/.codex/skills` or
  `~/.agents/skills`, resolve them against the active workspace root.
- When called from a repo-local skill folder, convert to the shortest safe
  skill-folder relative path only if doing so improves the local handoff.
- Do not hard-code absolute AlphaFlower filesystem paths in skill instructions.

## Required Sections

The report must make these visible:

- **Target Flow**: the intended architecture.
- **Current Implementation Flow**: grouped current behavior, including fast paths and exceptions.
- **Target vs Current Gap**: what differs, why it matters, and how to catch up.
- **Done / Not Done Priority**: status, priority score, rationale, next action.
- **Scoring Criteria**: weights used to pick the next relay task.
- **Color Semantics**: what each diagram color means.
- **Validation**: commands, screenshots, and pass/fail/block result.

## Mermaid Rules

- Use quoted node labels when text contains punctuation, Korean, slashes, or parentheses.
- Keep target and current diagrams separate.
- Group detailed implementation nodes when the current flow is more detailed than the target.
- Mark real gaps explicitly; do not hide fallback/dead-end branches.
- Use the same color classes in target/current diagrams:

```mermaid
classDef green fill:#e8f2ea,stroke:#bdd1c2,color:#1f2933,stroke-width:1.5px
classDef blue fill:#e8f0f7,stroke:#c2d3e0,color:#1f2933,stroke-width:1.5px
classDef amber fill:#fff4dc,stroke:#e7c88f,color:#1f2933,stroke-width:1.5px
classDef red fill:#fde9e6,stroke:#e8bab5,color:#1f2933,stroke-width:1.5px
classDef gray fill:#eef1ed,stroke:#d8e0da,color:#1f2933,stroke-width:1.5px
```

Color meanings:

- `green`: server-owned, validated, normal control path.
- `blue`: external/cloud projected model path.
- `amber`: sensitive/local-first/read/revision/reclassification path.
- `red`: blocked, restricted, unsupported, or gap path.
- `gray`: branch, decision, server template, or exact-control helper.

## Render Commands

Verify `mmdc` first:

```bash
command -v mmdc && mmdc --version
```

Generate PNGs:

```bash
mmdc -i path/to/target-flow.mmd -o path/to/target-flow.png -b transparent --scale 2
mmdc -i path/to/current-flow.mmd -o path/to/current-flow.png -b transparent --scale 2
```

If Chromium sandboxing fails, create a temporary Puppeteer config and pass `-p`.

## HTML Report Rules

- Embed PNGs with `<img>` tags and absolute/relative links that work from `file://`.
- Put color semantics next to the diagrams.
- Include gap and priority tables below the diagrams.
- Avoid huge inline SVG when `.mmd` + generated `.png` is available.
- Keep report pages static and self-contained enough to open directly in the browser.

## Validation

Use Playwright or Browser to verify:

- target image loads
- current image loads
- color legend appears
- gap table appears
- priority/scoring table appears when required

Minimal Playwright checks:

- image count >= 2
- each image has nonzero natural width/height
- required headings are visible
- screenshot is saved under `fivecircles/test/playwright-screenshots/` when the repo uses fivecircles

Do not mark workflow alignment as done unless the target/current visual comparison has been updated.
