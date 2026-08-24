---
name: blogger-html
description: Convert drafts, Markdown posts, notebook writeups, or analysis reports into Blogger.com-safe responsive HTML. Use when the user asks for Blogger/Blogspot-ready HTML, says copied content stretches sideways, needs tables/code blocks/images fixed for Blogger, or wants image insertion slots for Blogger's Insert image workflow.
---

# Blogger HTML

## Goal

Create Blogger.com HTML that does not break the post layout when pasted into Blogger's HTML view. Blogger is fragile with Markdown tables, long file names, wide code blocks, and local image paths, so convert drafts into constrained, responsive HTML.

## Workflow

1. Preserve the user's article structure and main wording.
2. Convert Markdown-like headings, paragraphs, lists, tables, code fences, blockquotes, and image references into Blogger-safe HTML.
3. Wrap the whole post in a constrained container:
   - `max-width: 760px`
   - centered with `margin: 0 auto`
   - `overflow-wrap: break-word`
4. Put tables inside a horizontal-scroll wrapper:
   - `.blog-table-wrap { max-width: 100%; overflow-x: auto; }`
   - use normal table markup inside it.
5. Put code blocks in wrapped/preformatted boxes:
   - `white-space: pre-wrap`
   - `overflow-x: auto`
   - `overflow-wrap: anywhere`
6. Replace local Markdown images with clear Blogger upload slots, unless the user gives public image URLs.
   - Example: `<div class="image-slot">여기에 1번 이미지 삽입: chart.png</div>`
7. Avoid raw local paths in the final Blogger HTML. Blogger cannot read local paths.
8. Shorten or avoid very long filenames in visible tables. Use descriptive labels instead.

## Script

Use `scripts/make_blogger_html.py` for repeatable conversion:

```bash
python3 ~/.codex/skills/blogger-html/scripts/make_blogger_html.py input.md -o output.html
```

Optional title:

```bash
python3 ~/.codex/skills/blogger-html/scripts/make_blogger_html.py input.md -o output.html --title "블로그 제목"
```

The script is intentionally dependency-free. It handles common Markdown used in analysis writeups:

- `#`, `##`, `###` headings
- fenced code blocks
- Markdown tables
- ordered and unordered lists
- blockquotes
- Markdown image syntax
- paragraphs and inline code/bold

After conversion, inspect the output for image slots. Tell the user to paste the HTML into Blogger's HTML view, then upload each image at the slot using Blogger's Insert image button.

## Blogger-Safe Rules

- Do not paste raw Markdown tables into Blogger compose mode.
- Do not leave unwrapped `<pre>` blocks.
- Do not leave long uninterrupted strings in visible text if they can be shortened.
- Do not assume images in `./assets`, `/Users/...`, or `blog_assets/...` will render after publishing.
- Prefer image slots for Blogger unless the user explicitly hosts images elsewhere and provides URLs.
- If the user wants a fully self-contained post, keep image slots and provide a numbered image upload checklist.

## Delivery

Return:

- path to the generated `.html`
- list of image files/slots to upload
- one sentence reminding the user to use Blogger HTML view

When a layout-stretching bug is reported, explain briefly that wide Markdown tables, long code lines, or local image paths can force Blogger's editor wider than the theme container.
