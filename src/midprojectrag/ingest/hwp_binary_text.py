from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence


def extract_paragraphs(path: Path) -> list[str]:
    from hwp5.binmodel import Hwp5File, ParaText

    document = Hwp5File(str(path))
    paragraphs: list[str] = []
    for section in document.bodytext.sections:
        for model in section.models():
            if model.get("type") is not ParaText:
                continue
            chunks = model.get("content", {}).get("chunks", [])
            text = "".join(
                chunk
                for _span, chunk in chunks
                if isinstance(chunk, str)
            ).replace("\x00", "").strip()
            if text:
                paragraphs.append(text)
    return paragraphs


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        return 2
    try:
        paragraphs = extract_paragraphs(Path(arguments[0]))
    except ModuleNotFoundError:
        return 4
    except Exception:
        return 5
    if not paragraphs:
        return 3
    sys.stdout.write("\n\n".join(paragraphs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
