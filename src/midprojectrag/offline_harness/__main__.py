"""Offline evaluation entrypoint; has no model/provider dependency."""
import argparse
import json
from pathlib import Path

from .replay import replay_saved_answers


def main(argv=None):
    parser = argparse.ArgumentParser(description="Provider-free saved-answer rescoring")
    parser.add_argument("command", choices=["rescore"])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--cases", type=Path, action="append", default=[])
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = replay_saved_answers(args.input, args.output_dir, data_root=args.data_root, case_paths=args.cases)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
