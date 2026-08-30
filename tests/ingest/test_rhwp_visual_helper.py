from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from midprojectrag.ingest.hwp_visual_v2 import (
    parse_hwp_helper_occurrences,
    recover_hwp_occurrences,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "rhwp_visual_helper.mjs"
DOC_ID = "doc_0123456789abcdef01234567"
BLOCK_ID = "block_0123456789abcdef01234567"


FAKE_CORE = r'''
export default async function init(options) {
  if (!options || !(options.module_or_path instanceof Uint8Array)) {
    throw new Error("bad wasm init");
  }
}

const IMAGE_BYTES = new Uint8Array([
  137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 0
]);

function layer(page) {
  const shared = {
    type: "image",
    bbox: page === 0
      ? {x: 10.04, y: 20.04, width: 30.04, height: 40.04}
      : {x: 5.04, y: 6.04, width: 20.04, height: 21.04},
    mime: "image/png",
    sourceImageKey: "bin:0:7:src",
    imageBytesOmitted: true
  };
  const children = [{ops: [shared]}];
  if (page === 0) {
    children.push({ops: [{
      type: "image",
      bbox: {x: 80, y: 90, width: 10, height: 11},
      mime: "image/png"
    }]});
  }
  return {
    pageWidth: 100,
    pageHeight: 200,
    root: {
      bounds: {x: 0, y: 0, width: 100, height: 200},
      children
    }
  };
}

function controls(page) {
  if (page === 0) {
    return {controls: [{
      type: "image",
      x: 10, y: 20, w: 30, h: 40,
      secIdx: 0, paraIdx: 7, controlIdx: 4,
      parentParaIdx: 7, outerTableControlIdx: 2,
      cellPath: [{controlIndex: 2, cellIndex: 1, cellParaIndex: 0}],
      stableIndex: [0, 7, 2, 1, 0, 4]
    }]};
  }
  return {controls: [{
    type: "image",
    x: 5, y: 6, w: 20, h: 21,
    secIdx: 0, paraIdx: 10, controlIdx: 1,
    stableIndex: [0, 10, 1]
  }]};
}

export class HwpDocument {
  constructor(data) {
    if (!(data instanceof Uint8Array) || typeof globalThis.measureTextWidth !== "function") {
      throw new Error("bad document init");
    }
    this.tooMany = data[0] === 255;
  }
  pageCount() { return this.tooMany ? 10001 : 2; }
  getPageLayerTreeWithProfile(page, profile, omit) {
    if (profile !== "screen" || omit !== true) throw new Error("bad profile");
    return JSON.stringify(layer(page));
  }
  getPageControlLayout(page) { return JSON.stringify(controls(page)); }
  getPageSourceImageKeys(page) {
    if (page !== 0 && page !== 1) throw new Error("bad page");
    return JSON.stringify({cacheable: true, keys: ["bin:0:7:src"]});
  }
  getSourceImageBytes(key) {
    if (key !== "bin:0:7:src") throw new Error("bad key");
    return IMAGE_BYTES;
  }
  renderPageSvg(page) {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="100" height="200"><rect width="100" height="200" fill="#fff"/><text>${page}</text></svg>`;
  }
  free() {}
}
'''


FAKE_CANVAS = r'''
const PNG = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3, 4]);

export function createCanvas(width, height) {
  return {
    width,
    height,
    getContext() {
      return {
        font: "",
        measureText(text) { return {width: String(text).length}; },
        clearRect() {},
        drawImage() {}
      };
    },
    toBuffer(kind) {
      if (kind !== "image/png") throw new Error("bad output kind");
      return PNG;
    }
  };
}

export async function loadImage(value) {
  if (!(value instanceof Uint8Array)) throw new Error("bad image input");
  return {ok: true};
}
'''


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RhwpVisualHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("node_unavailable")

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.private_root = self.root / "private"
        self.private_root.mkdir()
        self.input = self.root / "sample.hwp"
        self.input.write_bytes(b"synthetic-hwp")
        self.blocks = self.root / "blocks.jsonl"
        block = {
            "doc_id": DOC_ID,
            "block_id": BLOCK_ID,
            "table_structure": {
                "section": 0,
                "paragraph": 7,
                "control": 2,
                "cells": [
                    {"row": 0, "col": 0, "nested": []},
                    {"row": 0, "col": 1, "nested": []},
                ],
            },
        }
        self.blocks.write_text(json.dumps(block) + "\n", encoding="utf-8")
        self.core = self.root / "fake-core.mjs"
        self.core.write_text(FAKE_CORE, encoding="utf-8")
        self.wasm = self.root / "fake.wasm"
        self.wasm.write_bytes(b"fake-wasm")
        self.canvas = self.root / "fake-canvas.mjs"
        self.canvas.write_text(FAKE_CANVAS, encoding="utf-8")
        self.output = self.private_root / "result" / "helper.json"
        self.page_renders = self.private_root / "page-renders"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _command(
        self,
        *,
        source_sha256: str | None = None,
        core_sha256: str | None = None,
        output: Path | None = None,
        include_page_renders: bool = True,
    ) -> list[str]:
        command = [
            self.node,
            str(HELPER),
            "--input",
            str(self.input.resolve()),
            "--blocks",
            str(self.blocks.resolve()),
            "--doc-id",
            DOC_ID,
            "--source-sha256",
            source_sha256 or _sha256(self.input),
            "--core-js",
            str(self.core.resolve()),
            "--core-js-sha256",
            core_sha256 or _sha256(self.core),
            "--wasm",
            str(self.wasm.resolve()),
            "--wasm-sha256",
            _sha256(self.wasm),
            "--canvas-module",
            str(self.canvas.resolve()),
            "--canvas-sha256",
            _sha256(self.canvas),
            "--private-root",
            str(self.private_root.resolve()),
            "--output",
            str((output or self.output).resolve()),
        ]
        if include_page_renders:
            command.extend(["--page-render-dir", str(self.page_renders.resolve())])
        return command

    def _run(self, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self._command(**kwargs),
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def test_emits_strict_reusable_occurrences_assets_and_page_renders(self) -> None:
        first = self._run()
        self.assertEqual(first.returncode, 0, first.stderr)
        summary = json.loads(first.stdout)
        envelope = json.loads(self.output.read_text(encoding="utf-8"))

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["counts"]["image_ops_total"], 3)
        self.assertEqual(summary["counts"]["placed_occurrences"], 2)
        self.assertEqual(summary["counts"]["unresolved_occurrences"], 1)
        self.assertEqual(envelope["unresolved"]["bbox_match_ambiguous"], 1)
        self.assertNotIn("base64", self.output.read_text(encoding="utf-8"))

        helpers = parse_hwp_helper_occurrences(
            envelope["occurrences"], doc_id=DOC_ID
        )
        self.assertEqual(len(helpers), 2)
        nested = helpers[0]["source_anchor"]
        self.assertEqual(nested["kind"], "table_nested")
        self.assertEqual(nested["table_block_id"], BLOCK_ID)
        self.assertEqual(nested["cell_path"][0]["row"], 0)
        self.assertEqual(nested["cell_path"][0]["column"], 1)

        recovered = recover_hwp_occurrences(
            doc_id=DOC_ID,
            source_sha256=_sha256(self.input),
            helper_payload=envelope["occurrences"],
            source_objects=envelope["source_objects"],
        )
        self.assertEqual(len(recovered), 2)
        self.assertEqual(
            {row["source_object_status"] for row in recovered},
            {"exact_resource_link"},
        )
        self.assertEqual(len({row["source_object_id"] for row in recovered}), 1)

        self.assertEqual(len(envelope["source_assets"]), 1)
        asset = envelope["source_assets"][0]
        asset_path = self.private_root / asset["relpath"]
        self.assertTrue(asset_path.is_file())
        self.assertEqual(_sha256(asset_path), asset["source_object_sha256"])
        self.assertEqual(len(asset["source_image_key_sha256"]), 64)
        self.assertEqual(len(envelope["page_renders"]), 2)
        for render in envelope["page_renders"]:
            render_path = self.private_root / render["relpath"]
            self.assertTrue(render_path.is_file())
            self.assertEqual(_sha256(render_path), render["page_render_sha256"])
            self.assertEqual(render["coordinate_page_bbox"]["w"], 100)

        second = self._run()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout), summary)

    def test_rejects_pin_mismatch_without_writing_output(self) -> None:
        result = self._run(core_sha256="0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stderr)["error_code"],
            "rhwp_visual_helper_core_js_sha256_mismatch",
        )
        self.assertFalse(self.output.exists())

    def test_rejects_output_outside_private_root(self) -> None:
        outside = self.root / "outside.json"
        result = self._run(output=outside, include_page_renders=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stderr)["error_code"],
            "rhwp_visual_helper_output_invalid",
        )
        self.assertFalse(outside.exists())

    def test_rejects_symlinked_output_parent(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        linked = self.private_root / "linked"
        try:
            linked.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlink_unavailable")
        result = self._run(output=linked / "helper.json", include_page_renders=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stderr)["error_code"],
            "rhwp_visual_helper_output_invalid",
        )
        self.assertFalse((outside / "helper.json").exists())

    def test_rejects_page_count_over_bound(self) -> None:
        self.input.write_bytes(bytes([255]))
        result = self._run(include_page_renders=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stderr)["error_code"],
            "rhwp_visual_helper_page_count_invalid",
        )
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
