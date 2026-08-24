#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import re
from pathlib import Path


STYLE = """<style>
  .blogger-safe-post {
    box-sizing: border-box;
    max-width: 760px;
    margin: 0 auto;
    line-height: 1.75;
    font-size: 16px;
    color: #222;
    word-break: keep-all;
    overflow-wrap: break-word;
  }
  .blogger-safe-post * { box-sizing: border-box; }
  .blog-code {
    max-width: 100%;
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-word;
    overflow-wrap: anywhere;
    background: #f5f5f5;
    border: 1px solid #e6e6e6;
    border-radius: 8px;
    padding: 14px;
    font-size: 13px;
    line-height: 1.6;
  }
  .blog-table-wrap {
    max-width: 100%;
    overflow-x: auto;
    margin: 14px 0 22px;
    border: 1px solid #ececec;
    border-radius: 8px;
  }
  .blog-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
    table-layout: auto;
  }
  .blog-table th,
  .blog-table td {
    border-bottom: 1px solid #ececec;
    padding: 10px 12px;
    vertical-align: top;
    overflow-wrap: anywhere;
  }
  .blog-table th {
    background: #f7f7f7;
    font-weight: 700;
    text-align: left;
  }
  .image-slot {
    border: 1px dashed #bbb;
    background: #fafafa;
    border-radius: 8px;
    padding: 18px;
    margin: 18px 0;
    color: #666;
    text-align: center;
    font-size: 14px;
  }
  .blogger-safe-post h1 { font-size: 28px; line-height: 1.35; margin: 0 0 18px; }
  .blogger-safe-post h2 { margin-top: 36px; font-size: 24px; line-height: 1.4; }
  .blogger-safe-post h3 { margin-top: 28px; font-size: 19px; line-height: 1.45; }
  .blogger-safe-post code {
    background: #f5f5f5;
    border-radius: 4px;
    padding: 1px 4px;
    overflow-wrap: anywhere;
  }
  .blogger-safe-post blockquote {
    border-left: 4px solid #ddd;
    margin: 18px 0;
    padding: 8px 16px;
    color: #555;
    background: #fafafa;
  }
  .blogger-safe-post img {
    max-width: 100%;
    height: auto;
  }
</style>"""


IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")


def inline_format(text: str) -> str:
    escaped = html.escape(text)
    escaped = INLINE_CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", escaped)
    escaped = BOLD_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", escaped)
    return escaped


def is_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def parse_table(lines: list[str], start: int) -> tuple[str, int]:
    rows: list[list[str]] = []
    i = start
    while i < len(lines) and "|" in lines[i] and lines[i].strip():
        if i == start + 1 and is_table_separator(lines[i]):
            i += 1
            continue
        cells = [cell.strip() for cell in lines[i].strip().strip("|").split("|")]
        rows.append(cells)
        i += 1

    if not rows:
        return "", start

    max_cols = max(len(row) for row in rows)
    normalized = [row + [""] * (max_cols - len(row)) for row in rows]
    head, body = normalized[0], normalized[1:]

    out = ['<div class="blog-table-wrap">', '<table class="blog-table">', "<thead>", "<tr>"]
    for cell in head:
        out.append(f"<th>{inline_format(cell)}</th>")
    out.extend(["</tr>", "</thead>", "<tbody>"])
    for row in body:
        out.append("<tr>")
        for cell in row:
            out.append(f"<td>{inline_format(cell)}</td>")
        out.append("</tr>")
    out.extend(["</tbody>", "</table>", "</div>"])
    return "\n".join(out), i


def image_html(alt: str, src: str, slot_number: int) -> str:
    clean_src = src.strip()
    name = Path(clean_src).name or clean_src
    if re.match(r"https?://", clean_src):
        return f'<img src="{html.escape(clean_src)}" alt="{html.escape(alt)}" />'
    return f'<div class="image-slot">여기에 {slot_number}번 이미지 삽입: {html.escape(name)}</div>'


def convert_markdown_to_blogger_html(markdown: str, title: str | None = None) -> str:
    lines = markdown.splitlines()
    out: list[str] = [STYLE, '<div class="blogger-safe-post">']
    if title:
        out.append(f"<h1>{inline_format(title)}</h1>")

    i = 0
    image_count = 0
    in_code = False
    code_lines: list[str] = []
    list_type: str | None = None

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            if not in_code:
                close_list()
                in_code = True
                code_lines = []
            else:
                out.append(f'<pre class="blog-code"><code>{html.escape(chr(10).join(code_lines))}</code></pre>')
                in_code = False
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        if not stripped:
            close_list()
            i += 1
            continue

        if "|" in stripped and i + 1 < len(lines) and is_table_separator(lines[i + 1]):
            close_list()
            table_html, i = parse_table(lines, i)
            out.append(table_html)
            continue

        image_match = IMAGE_RE.fullmatch(stripped)
        if image_match:
            close_list()
            image_count += 1
            out.append(image_html(image_match.group(1), image_match.group(2), image_count))
            i += 1
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline_format(heading.group(2))}</h{level}>")
            i += 1
            continue

        if stripped.startswith(">"):
            close_list()
            quote = stripped.lstrip(">").strip()
            out.append(f"<blockquote>{inline_format(quote)}</blockquote>")
            i += 1
            continue

        ordered = re.match(r"^\d+\.\s+(.+)$", stripped)
        unordered = re.match(r"^[-*]\s+(.+)$", stripped)
        if ordered or unordered:
            desired = "ol" if ordered else "ul"
            content = ordered.group(1) if ordered else unordered.group(1)
            if list_type != desired:
                close_list()
                out.append(f"<{desired}>")
                list_type = desired
            out.append(f"<li>{inline_format(content)}</li>")
            i += 1
            continue

        close_list()
        replaced = []
        cursor = 0
        matched_image = False
        for match in IMAGE_RE.finditer(line):
            matched_image = True
            if match.start() > cursor:
                replaced.append(inline_format(line[cursor:match.start()]))
            image_count += 1
            replaced.append(image_html(match.group(1), match.group(2), image_count))
            cursor = match.end()
        if matched_image:
            if cursor < len(line):
                replaced.append(inline_format(line[cursor:]))
            out.append("".join(replaced))
        else:
            out.append(f"<p>{inline_format(stripped)}</p>")
        i += 1

    if in_code:
        out.append(f'<pre class="blog-code"><code>{html.escape(chr(10).join(code_lines))}</code></pre>')
    close_list()
    out.append("</div>")
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Markdown-ish draft to Blogger-safe HTML.")
    parser.add_argument("input", type=Path, help="Input Markdown/text file")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output HTML file")
    parser.add_argument("--title", help="Optional title inserted as h1")
    args = parser.parse_args()

    source = args.input.read_text(encoding="utf-8")
    output = convert_markdown_to_blogger_html(source, title=args.title)
    args.output.write_text(output, encoding="utf-8")
    print(f"Wrote Blogger-safe HTML: {args.output}")


if __name__ == "__main__":
    main()
