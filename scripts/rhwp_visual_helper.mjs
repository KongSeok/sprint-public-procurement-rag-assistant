#!/usr/bin/env node

/**
 * Pinned, network-free bridge from @rhwp/core's WASM layout APIs to the
 * private HWP visual-v2 helper contract.
 *
 * The program intentionally accepts only explicit absolute paths and SHA-256
 * pins. Binary image payloads are written content-addressed below
 * --private-root; JSON contains hashes and relative paths, never bytes/base64.
 */

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const HELPER_SCHEMA_VERSION = "1.0";
const COORDINATE_SPACE = "rhwp_css_px_96dpi";
const RENDER_PROFILE = "screen";
const MAX_SOURCE_BYTES = 512 * 1024 * 1024;
const MAX_BLOCKS_BYTES = 128 * 1024 * 1024;
const MAX_MODULE_BYTES = 128 * 1024 * 1024;
const MAX_WASM_BYTES = 512 * 1024 * 1024;
const MAX_JSON_RESULT_BYTES = 64 * 1024 * 1024;
const MAX_METHOD_JSON_BYTES = 64 * 1024 * 1024;
const MAX_ASSET_BYTES = 64 * 1024 * 1024;
const MAX_TOTAL_ASSET_BYTES = 512 * 1024 * 1024;
const MAX_PAGES = 10_000;
const MAX_BLOCKS = 100_000;
const MAX_OCCURRENCES = 100_000;
const MAX_SOURCE_OBJECTS = 100_000;
const MAX_TREE_NODES = 1_000_000;
const MAX_PAGE_DIMENSION = 100_000;
const MAX_PAGE_PIXELS = 100_000_000;
const MAX_KEY_CHARS = 256;
const BBOX_TOLERANCE_PX = 0.125;
const SHA256_RE = /^[0-9a-f]{64}$/;
const DOC_ID_RE = /^doc_[0-9a-f]{24}$/;
const BLOCK_ID_RE = /^block_[0-9a-f]{24}$/;
const MEDIA_TYPE_RE = /^(?:image|application)\/[A-Za-z0-9.+-]+$/;

class HelperError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

function fail(code) {
  throw new HelperError(code);
}

function parseArgs(argv) {
  const allowed = new Set([
    "input",
    "blocks",
    "doc-id",
    "source-sha256",
    "core-js",
    "core-js-sha256",
    "wasm",
    "wasm-sha256",
    "canvas-module",
    "canvas-sha256",
    "private-root",
    "output",
    "asset-dir",
    "page-render-dir",
  ]);
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const rawName = argv[index];
    const value = argv[index + 1];
    if (
      typeof rawName !== "string" ||
      !rawName.startsWith("--") ||
      value === undefined ||
      value.startsWith("--")
    ) {
      fail("rhwp_visual_helper_arguments_invalid");
    }
    const name = rawName.slice(2);
    if (!allowed.has(name) || Object.hasOwn(result, name)) {
      fail("rhwp_visual_helper_arguments_invalid");
    }
    result[name] = value;
  }
  const required = [
    "input",
    "blocks",
    "doc-id",
    "source-sha256",
    "core-js",
    "core-js-sha256",
    "wasm",
    "wasm-sha256",
    "canvas-module",
    "canvas-sha256",
    "private-root",
    "output",
  ];
  if (required.some((name) => !Object.hasOwn(result, name))) {
    fail("rhwp_visual_helper_arguments_invalid");
  }
  if (!DOC_ID_RE.test(result["doc-id"])) {
    fail("rhwp_visual_helper_doc_id_invalid");
  }
  for (const name of [
    "source-sha256",
    "core-js-sha256",
    "wasm-sha256",
    "canvas-sha256",
  ]) {
    if (!SHA256_RE.test(result[name])) {
      fail("rhwp_visual_helper_pin_invalid");
    }
  }
  return result;
}

function assertAbsolute(candidate, code) {
  if (typeof candidate !== "string" || !path.isAbsolute(candidate)) {
    fail(code);
  }
  return path.resolve(candidate);
}

function assertExistingRegularFile(candidate, maxBytes, code) {
  const resolved = assertAbsolute(candidate, code);
  let stat;
  let real;
  try {
    stat = fs.lstatSync(resolved);
    real = fs.realpathSync(resolved);
  } catch {
    fail(code);
  }
  if (!stat.isFile() || stat.isSymbolicLink() || real !== resolved) {
    fail(code);
  }
  if (!Number.isSafeInteger(stat.size) || stat.size < 1 || stat.size > maxBytes) {
    fail(`${code}_size_exceeded`);
  }
  return { path: resolved, size: stat.size };
}

function assertExistingDirectory(candidate, code) {
  const resolved = assertAbsolute(candidate, code);
  let stat;
  let real;
  try {
    stat = fs.lstatSync(resolved);
    real = fs.realpathSync(resolved);
  } catch {
    fail(code);
  }
  if (!stat.isDirectory() || stat.isSymbolicLink() || real !== resolved) {
    fail(code);
  }
  return resolved;
}

function isContained(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== "..");
}

function assertNoSymlinkComponents(root, candidate, code) {
  const relative = path.relative(root, candidate);
  const components = relative === "" ? [] : relative.split(path.sep);
  let current = root;
  for (const component of components) {
    current = path.join(current, component);
    if (!fs.existsSync(current)) break;
    let stat;
    try {
      stat = fs.lstatSync(current);
    } catch {
      fail(code);
    }
    if (stat.isSymbolicLink() || fs.realpathSync(current) !== current) fail(code);
  }
}

function prepareOutputDirectory(root, candidate, code, { allowRoot = false } = {}) {
  const resolved = assertAbsolute(candidate, code);
  if (!isContained(root, resolved) || (!allowRoot && resolved === root)) {
    fail(code);
  }
  assertNoSymlinkComponents(root, resolved, code);
  try {
    fs.mkdirSync(resolved, { recursive: true, mode: 0o700 });
  } catch {
    fail(code);
  }
  let real;
  let stat;
  try {
    real = fs.realpathSync(resolved);
    stat = fs.lstatSync(resolved);
  } catch {
    fail(code);
  }
  if (
    real !== resolved ||
    !isContained(root, real) ||
    !stat.isDirectory() ||
    stat.isSymbolicLink()
  ) {
    fail(code);
  }
  return resolved;
}

function prepareOutputFile(root, candidate, code) {
  const resolved = assertAbsolute(candidate, code);
  if (!isContained(root, resolved) || resolved === root) {
    fail(code);
  }
  const parent = prepareOutputDirectory(root, path.dirname(resolved), code, { allowRoot: true });
  const rebuilt = path.join(parent, path.basename(resolved));
  if (rebuilt !== resolved) {
    fail(code);
  }
  if (fs.existsSync(resolved)) {
    let stat;
    try {
      stat = fs.lstatSync(resolved);
    } catch {
      fail(code);
    }
    if (!stat.isFile() || stat.isSymbolicLink() || fs.realpathSync(resolved) !== resolved) {
      fail(code);
    }
  }
  return resolved;
}

function sha256Bytes(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

function readPinnedFile(file, expected, errorCode) {
  let bytes;
  try {
    bytes = fs.readFileSync(file.path);
  } catch {
    fail(`${errorCode}_read_failed`);
  }
  if (sha256Bytes(bytes) !== expected) {
    fail(`${errorCode}_mismatch`);
  }
  return bytes;
}

function canonicalize(value) {
  if (Array.isArray(value)) {
    return value.map(canonicalize);
  }
  if (value !== null && typeof value === "object") {
    const result = {};
    for (const key of Object.keys(value).sort()) {
      result[key] = canonicalize(value[key]);
    }
    return result;
  }
  return value;
}

function canonicalJson(value) {
  return JSON.stringify(canonicalize(value));
}

let temporaryCounter = 0;

function writeContentVerified(destination, bytes, expectedSha256, mismatchCode) {
  if (sha256Bytes(bytes) !== expectedSha256) {
    fail(`${mismatchCode}_digest_invalid`);
  }
  if (fs.existsSync(destination)) {
    let existing;
    let stat;
    try {
      stat = fs.lstatSync(destination);
      existing = fs.readFileSync(destination);
    } catch {
      fail(mismatchCode);
    }
    if (
      !stat.isFile() ||
      stat.isSymbolicLink() ||
      fs.realpathSync(destination) !== destination ||
      sha256Bytes(existing) !== expectedSha256
    ) {
      fail(mismatchCode);
    }
    return;
  }
  const parent = path.dirname(destination);
  const temporary = path.join(
    parent,
    `.${path.basename(destination)}.${process.pid}.${temporaryCounter += 1}.tmp`,
  );
  try {
    const handle = fs.openSync(temporary, "wx", 0o600);
    try {
      fs.writeFileSync(handle, bytes);
      fs.fsyncSync(handle);
    } finally {
      fs.closeSync(handle);
    }
    fs.linkSync(temporary, destination);
    fs.unlinkSync(temporary);
  } catch (error) {
    try {
      if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
    } catch {
      // Preserve the stable write error below.
    }
    if (error && error.code === "EEXIST" && fs.existsSync(destination)) {
      const existing = fs.readFileSync(destination);
      if (sha256Bytes(existing) === expectedSha256) return;
    }
    fail(`${mismatchCode}_write_failed`);
  }
}

function parseBoundedJson(raw, code) {
  if (typeof raw !== "string" || Buffer.byteLength(raw, "utf8") > MAX_METHOD_JSON_BYTES) {
    fail(code);
  }
  try {
    return JSON.parse(raw);
  } catch {
    fail(code);
  }
}

function nonnegativeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function finiteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function normalizeNumber(value, code) {
  if (!finiteNumber(value)) fail(code);
  const rounded = Math.round(value * 1_000_000) / 1_000_000;
  return Object.is(rounded, -0) ? 0 : rounded;
}

function normalizeBBox(value, code) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(code);
  const x = normalizeNumber(value.x, code);
  const y = normalizeNumber(value.y, code);
  const w = normalizeNumber(value.w ?? value.width, code);
  const h = normalizeNumber(value.h ?? value.height, code);
  if (w <= 0 || h <= 0) fail(code);
  return { x, y, w, h };
}

function validKey(value) {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= MAX_KEY_CHARS &&
    !Array.from(value).some((character) => {
      const code = character.codePointAt(0);
      return code < 0x20 || code === 0x7f;
    })
  );
}

function loadTableIndex(blocksPath, docId) {
  let raw;
  try {
    raw = fs.readFileSync(blocksPath, "utf8");
  } catch {
    fail("rhwp_visual_helper_blocks_read_failed");
  }
  const lines = raw.split(/\r?\n/);
  if (lines.at(-1) === "") lines.pop();
  if (lines.length > MAX_BLOCKS || lines.some((line) => line.trim() === "")) {
    fail("rhwp_visual_helper_blocks_invalid");
  }
  const tables = new Map();
  for (const line of lines) {
    let block;
    try {
      block = JSON.parse(line);
    } catch {
      fail("rhwp_visual_helper_blocks_invalid");
    }
    if (
      !block ||
      typeof block !== "object" ||
      Array.isArray(block) ||
      block.doc_id !== docId ||
      typeof block.block_id !== "string" ||
      !BLOCK_ID_RE.test(block.block_id)
    ) {
      fail("rhwp_visual_helper_blocks_invalid");
    }
    const table = block.table_structure;
    if (table === undefined || table === null) continue;
    if (
      !table ||
      typeof table !== "object" ||
      Array.isArray(table) ||
      !nonnegativeInteger(table.section) ||
      !nonnegativeInteger(table.paragraph) ||
      !nonnegativeInteger(table.control) ||
      !Array.isArray(table.cells)
    ) {
      fail("rhwp_visual_helper_table_structure_invalid");
    }
    const key = `${table.section}:${table.paragraph}:${table.control}`;
    if (tables.has(key)) fail("rhwp_visual_helper_table_anchor_ambiguous");
    tables.set(key, { blockId: block.block_id, table });
  }
  return tables;
}

function cellCoordinates(table, cellIndex) {
  if (!table || !Array.isArray(table.cells) || !nonnegativeInteger(cellIndex)) return null;
  const cell = table.cells[cellIndex];
  if (
    !cell ||
    typeof cell !== "object" ||
    Array.isArray(cell) ||
    !nonnegativeInteger(cell.row) ||
    !nonnegativeInteger(cell.col)
  ) {
    return null;
  }
  return { row: cell.row, column: cell.col, cell };
}

function sourceAnchorFromControl(control, tables) {
  if (!control || typeof control !== "object" || Array.isArray(control)) return null;
  if (
    !nonnegativeInteger(control.secIdx) ||
    !nonnegativeInteger(control.paraIdx) ||
    !nonnegativeInteger(control.controlIdx)
  ) {
    return null;
  }
  const rawPath = control.cellPath;
  if (!Array.isArray(rawPath) || rawPath.length === 0) {
    return {
      kind: "body",
      section_index: control.secIdx,
      paragraph_index: control.paraIdx,
      control_index: control.controlIdx,
      table_block_id: null,
      cell_path: [],
    };
  }
  if (rawPath.length > 32) return null;
  const parentParagraph = control.parentParaIdx;
  const outerControl = control.outerTableControlIdx ?? rawPath[0]?.controlIndex;
  if (!nonnegativeInteger(parentParagraph) || !nonnegativeInteger(outerControl)) return null;
  const outer = tables.get(`${control.secIdx}:${parentParagraph}:${outerControl}`);
  if (!outer) return null;
  let currentTable = outer.table;
  const normalizedPath = [];
  for (let index = 0; index < rawPath.length; index += 1) {
    const segment = rawPath[index];
    if (
      !segment ||
      typeof segment !== "object" ||
      Array.isArray(segment) ||
      !nonnegativeInteger(segment.controlIndex) ||
      !nonnegativeInteger(segment.cellIndex) ||
      !nonnegativeInteger(segment.cellParaIndex)
    ) {
      return null;
    }
    const coordinates = cellCoordinates(currentTable, segment.cellIndex);
    if (!coordinates) return null;
    normalizedPath.push({
      control_index: segment.controlIndex,
      cell_index: segment.cellIndex,
      cell_paragraph_index: segment.cellParaIndex,
      row: coordinates.row,
      column: coordinates.column,
    });
    if (index + 1 < rawPath.length) {
      const nextControl = rawPath[index + 1]?.controlIndex;
      const nested = Array.isArray(coordinates.cell.nested) ? coordinates.cell.nested : [];
      const candidates = nested.filter(
        (value) =>
          value &&
          typeof value === "object" &&
          !Array.isArray(value) &&
          value.control === nextControl &&
          Array.isArray(value.cells),
      );
      if (candidates.length !== 1) return null;
      currentTable = candidates[0];
    }
  }
  return {
    kind: "table_nested",
    section_index: control.secIdx,
    paragraph_index: parentParagraph,
    control_index: control.controlIdx,
    table_block_id: outer.blockId,
    cell_path: normalizedPath,
  };
}

function extractImageOps(root) {
  const stack = [root];
  const result = [];
  let nodes = 0;
  let traversalIndex = 0;
  while (stack.length > 0) {
    const value = stack.pop();
    nodes += 1;
    if (nodes > MAX_TREE_NODES) fail("rhwp_visual_helper_layer_tree_limit_exceeded");
    if (!value || typeof value !== "object") continue;
    if (Array.isArray(value)) {
      for (let index = value.length - 1; index >= 0; index -= 1) stack.push(value[index]);
      continue;
    }
    if (value.type === "image") {
      let bbox;
      try {
        bbox = normalizeBBox(value.bbox, "rhwp_visual_helper_image_bbox_invalid");
      } catch (error) {
        if (error instanceof HelperError) {
          traversalIndex += 1;
          continue;
        }
        throw error;
      }
      const sourceImageKey = validKey(value.sourceImageKey) ? value.sourceImageKey : null;
      const mime = normalizeMediaType(value.mime, null);
      result.push({
        bbox,
        sourceImageKey,
        mime,
        inlineBase64: sourceImageKey === null && typeof value.base64 === "string" ? value.base64 : null,
        traversalIndex,
      });
      traversalIndex += 1;
    }
    const values = Object.values(value);
    for (let index = values.length - 1; index >= 0; index -= 1) stack.push(values[index]);
  }
  return result;
}

function bboxTightEqual(left, right) {
  return ["x", "y", "w", "h"].every(
    (field) => Math.abs(left[field] - right[field]) <= BBOX_TOLERANCE_PX,
  );
}

function matchOpsToControls(ops, rawControls, tables) {
  if (!Array.isArray(rawControls)) fail("rhwp_visual_helper_control_layout_invalid");
  const controls = [];
  for (const raw of rawControls) {
    if (!raw || typeof raw !== "object" || raw.type !== "image") continue;
    let bbox;
    try {
      bbox = normalizeBBox(raw, "rhwp_visual_helper_control_bbox_invalid");
    } catch (error) {
      if (error instanceof HelperError) continue;
      throw error;
    }
    controls.push({ raw, bbox, anchor: sourceAnchorFromControl(raw, tables) });
  }
  const opEdges = ops.map((op) =>
    controls
      .map((control, index) => (bboxTightEqual(op.bbox, control.bbox) ? index : -1))
      .filter((index) => index >= 0),
  );
  const controlDegree = new Array(controls.length).fill(0);
  for (const edges of opEdges) for (const index of edges) controlDegree[index] += 1;
  return ops.map((op, index) => {
    const edges = opEdges[index];
    if (edges.length !== 1 || controlDegree[edges[0]] !== 1) {
      return { op, anchor: null, control: null, reason: "bbox_match_ambiguous" };
    }
    const control = controls[edges[0]];
    if (!control.anchor) {
      return { op, anchor: null, control: control.raw, reason: "source_anchor_unresolved" };
    }
    return { op, anchor: control.anchor, control: control.raw, reason: null };
  });
}

function normalizeMediaType(value, fallback) {
  if (typeof value === "string" && value.length <= 128 && MEDIA_TYPE_RE.test(value)) {
    return value.toLowerCase();
  }
  return fallback;
}

function sniffMediaType(bytes) {
  if (bytes.length >= 8 && bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
    return "image/png";
  }
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return "image/jpeg";
  }
  if (bytes.length >= 6 && (bytes.subarray(0, 6).toString("ascii") === "GIF87a" || bytes.subarray(0, 6).toString("ascii") === "GIF89a")) {
    return "image/gif";
  }
  if (bytes.length >= 2 && bytes.subarray(0, 2).toString("ascii") === "BM") {
    return "image/bmp";
  }
  if (
    bytes.length >= 4 &&
    (bytes.subarray(0, 4).equals(Buffer.from([0x49, 0x49, 0x2a, 0x00])) ||
      bytes.subarray(0, 4).equals(Buffer.from([0x4d, 0x4d, 0x00, 0x2a])))
  ) {
    return "image/tiff";
  }
  if (
    bytes.length >= 12 &&
    bytes.subarray(0, 4).toString("ascii") === "RIFF" &&
    bytes.subarray(8, 12).toString("ascii") === "WEBP"
  ) {
    return "image/webp";
  }
  if (bytes.length >= 4 && bytes.subarray(0, 4).equals(Buffer.from([0xd7, 0xcd, 0xc6, 0x9a]))) {
    return "image/wmf";
  }
  const prefix = bytes.subarray(0, Math.min(bytes.length, 512)).toString("utf8").trimStart();
  if (prefix.startsWith("<svg") || prefix.startsWith("<?xml")) return "image/svg+xml";
  return "application/octet-stream";
}

function extensionFor(mediaType) {
  return {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "image/gif": "gif",
    "image/wmf": "wmf",
  }[mediaType] ?? "bin";
}

function isSupportedMedia(mediaType) {
  return new Set([
    "image/png",
    "image/jpeg",
    "image/bmp",
    "image/tiff",
    "image/webp",
    "image/svg+xml",
  ]).has(mediaType);
}

function decodeInlineBase64(value) {
  if (typeof value !== "string" || value.length === 0 || value.length > MAX_ASSET_BYTES * 2) {
    return null;
  }
  const normalized = value.replace(/\s+/g, "");
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(normalized)) return null;
  let bytes;
  try {
    bytes = Buffer.from(normalized, "base64");
  } catch {
    return null;
  }
  if (bytes.length < 1 || bytes.length > MAX_ASSET_BYTES) return null;
  const inputCanonical = normalized.replace(/=+$/, "");
  const outputCanonical = bytes.toString("base64").replace(/=+$/, "");
  return inputCanonical === outputCanonical ? bytes : null;
}

function stableControlIndex(control) {
  if (Array.isArray(control?.stableIndex) && control.stableIndex.every(nonnegativeInteger)) {
    return control.stableIndex;
  }
  return [control?.secIdx ?? 0, control?.paraIdx ?? 0, control?.controlIdx ?? 0];
}

function compareArrays(left, right) {
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    const a = left[index] ?? -1;
    const b = right[index] ?? -1;
    if (a !== b) return a - b;
  }
  return 0;
}

function occurrenceSort(left, right) {
  const controlOrder = compareArrays(stableControlIndex(left.control), stableControlIndex(right.control));
  if (controlOrder !== 0) return controlOrder;
  for (const field of ["y", "x", "h", "w"]) {
    const delta = left.op.bbox[field] - right.op.bbox[field];
    if (delta !== 0) return delta;
  }
  const leftKey = left.op.sourceImageKey ?? "";
  const rightKey = right.op.sourceImageKey ?? "";
  const keyOrder = leftKey.localeCompare(rightKey, "en");
  if (keyOrder !== 0) return keyOrder;
  return left.op.traversalIndex - right.op.traversalIndex;
}

function safeRelative(root, destination, code) {
  const relative = path.relative(root, destination);
  if (!relative || relative.startsWith(`..${path.sep}`) || relative === ".." || path.isAbsolute(relative)) {
    fail(code);
  }
  return relative.split(path.sep).join("/");
}

function uniqueAnchor(anchors) {
  const byCanonical = new Map();
  for (const anchor of anchors) byCanonical.set(canonicalJson(anchor), anchor);
  return byCanonical.size === 1 ? [...byCanonical.values()][0] : null;
}

async function renderAcceptedPages({ doc, canvasModule, pageRecords, pageSizes, pageRenderDir, privateRoot }) {
  if (!pageRenderDir) return [];
  if (typeof doc.renderPageSvg !== "function" || typeof canvasModule.loadImage !== "function") {
    fail("rhwp_visual_helper_page_renderer_unavailable");
  }
  const acceptedPages = [...new Set(pageRecords.map((row) => row.page))].sort((a, b) => a - b);
  const sizes = new Map(pageSizes.map((row) => [row.page, row]));
  const result = [];
  for (const page of acceptedPages) {
    const size = sizes.get(page);
    if (!size) fail("rhwp_visual_helper_page_size_missing");
    const pixelWidth = Math.ceil(size.width);
    const pixelHeight = Math.ceil(size.height);
    if (
      pixelWidth < 1 ||
      pixelHeight < 1 ||
      pixelWidth > MAX_PAGE_DIMENSION ||
      pixelHeight > MAX_PAGE_DIMENSION ||
      pixelWidth * pixelHeight > MAX_PAGE_PIXELS
    ) {
      fail("rhwp_visual_helper_page_render_dimensions_invalid");
    }
    let svg;
    try {
      svg = doc.renderPageSvg(page - 1);
    } catch {
      fail("rhwp_visual_helper_page_render_failed");
    }
    if (
      typeof svg !== "string" ||
      svg.length < 1 ||
      Buffer.byteLength(svg, "utf8") > MAX_METHOD_JSON_BYTES ||
      /(?:href|src)\s*=\s*["'](?:https?:|file:|\/\/)/i.test(svg) ||
      /url\(\s*["']?(?:https?:|file:|\/\/)/i.test(svg)
    ) {
      fail("rhwp_visual_helper_page_svg_invalid");
    }
    let png;
    try {
      const image = await canvasModule.loadImage(Buffer.from(svg, "utf8"));
      const canvas = canvasModule.createCanvas(pixelWidth, pixelHeight);
      const context = canvas.getContext("2d");
      context.clearRect?.(0, 0, pixelWidth, pixelHeight);
      context.drawImage(image, 0, 0, pixelWidth, pixelHeight);
      png = Buffer.from(canvas.toBuffer("image/png"));
    } catch {
      fail("rhwp_visual_helper_page_rasterize_failed");
    }
    if (png.length < 1 || png.length > MAX_ASSET_BYTES) {
      fail("rhwp_visual_helper_page_render_size_exceeded");
    }
    const digest = sha256Bytes(png);
    const destination = path.join(pageRenderDir, `${digest}.png`);
    writeContentVerified(destination, png, digest, "rhwp_visual_helper_page_render_existing_mismatch");
    result.push({
      page,
      width: pixelWidth,
      height: pixelHeight,
      coordinate_page_bbox: size.coordinate_page_bbox,
      page_render_sha256: digest,
      relpath: safeRelative(privateRoot, destination, "rhwp_visual_helper_page_render_path_invalid"),
      render_profile: {
        renderer: "rhwp_core_renderPageSvg+napi_canvas",
        profile: RENDER_PROFILE,
        scale: 1,
        pixel_rounding: "ceil",
      },
    });
  }
  return result;
}

async function run() {
  const args = parseArgs(process.argv.slice(2));
  const input = assertExistingRegularFile(args.input, MAX_SOURCE_BYTES, "rhwp_visual_helper_input_invalid");
  const blocks = assertExistingRegularFile(args.blocks, MAX_BLOCKS_BYTES, "rhwp_visual_helper_blocks_invalid");
  const coreJs = assertExistingRegularFile(args["core-js"], MAX_MODULE_BYTES, "rhwp_visual_helper_core_js_invalid");
  const wasm = assertExistingRegularFile(args.wasm, MAX_WASM_BYTES, "rhwp_visual_helper_wasm_invalid");
  const canvasEntry = assertExistingRegularFile(args["canvas-module"], MAX_MODULE_BYTES, "rhwp_visual_helper_canvas_invalid");
  const privateRoot = assertExistingDirectory(args["private-root"], "rhwp_visual_helper_private_root_invalid");
  const output = prepareOutputFile(privateRoot, args.output, "rhwp_visual_helper_output_invalid");
  const assetDir = prepareOutputDirectory(
    privateRoot,
    args["asset-dir"] ?? path.join(privateRoot, "source-objects"),
    "rhwp_visual_helper_asset_dir_invalid",
  );
  const pageRenderDir = args["page-render-dir"]
    ? prepareOutputDirectory(privateRoot, args["page-render-dir"], "rhwp_visual_helper_page_render_dir_invalid")
    : null;

  const sourceBytes = readPinnedFile(input, args["source-sha256"], "rhwp_visual_helper_source_sha256");
  readPinnedFile(coreJs, args["core-js-sha256"], "rhwp_visual_helper_core_js_sha256");
  const wasmBytes = readPinnedFile(wasm, args["wasm-sha256"], "rhwp_visual_helper_wasm_sha256");
  readPinnedFile(canvasEntry, args["canvas-sha256"], "rhwp_visual_helper_canvas_sha256");
  const tables = loadTableIndex(blocks.path, args["doc-id"]);

  let canvasModule;
  let coreModule;
  try {
    canvasModule = await import(pathToFileURL(canvasEntry.path).href);
    if (typeof canvasModule.createCanvas !== "function") fail("rhwp_visual_helper_canvas_contract_invalid");
    const measurementCanvas = canvasModule.createCanvas(8, 8);
    const measurementContext = measurementCanvas.getContext("2d");
    let lastFont = null;
    globalThis.measureTextWidth = (font, text) => {
      if (font !== lastFont) {
        measurementContext.font = font;
        lastFont = font;
      }
      return measurementContext.measureText(text).width;
    };
    coreModule = await import(pathToFileURL(coreJs.path).href);
    if (typeof coreModule.default !== "function" || typeof coreModule.HwpDocument !== "function") {
      fail("rhwp_visual_helper_core_contract_invalid");
    }
    await coreModule.default({ module_or_path: wasmBytes });
  } catch (error) {
    if (error instanceof HelperError) throw error;
    fail("rhwp_visual_helper_runtime_init_failed");
  }

  let doc;
  try {
    doc = new coreModule.HwpDocument(new Uint8Array(sourceBytes));
  } catch {
    fail("rhwp_visual_helper_document_open_failed");
  }

  try {
    const pageCount = doc.pageCount();
    if (!Number.isSafeInteger(pageCount) || pageCount < 1 || pageCount > MAX_PAGES) {
      fail("rhwp_visual_helper_page_count_invalid");
    }
    const candidatesByPage = [];
    const pageSizes = [];
    const pageKeySets = [];
    const sourceKeys = new Set();
    const keyMimes = new Map();
    const inlineAssets = new Map();
    const unresolvedCounts = {
      bbox_match_ambiguous: 0,
      source_anchor_unresolved: 0,
      source_key_not_listed: 0,
      inline_bytes_invalid: 0,
    };
    let imageOpsTotal = 0;
    let pagesWithImageOps = 0;

    for (let pageIndex = 0; pageIndex < pageCount; pageIndex += 1) {
      let layer;
      let layout;
      let keyEnvelope;
      try {
        layer = parseBoundedJson(
          doc.getPageLayerTreeWithProfile(pageIndex, RENDER_PROFILE, true),
          "rhwp_visual_helper_layer_tree_invalid",
        );
        layout = parseBoundedJson(
          doc.getPageControlLayout(pageIndex),
          "rhwp_visual_helper_control_layout_invalid",
        );
        keyEnvelope = parseBoundedJson(
          doc.getPageSourceImageKeys(pageIndex),
          "rhwp_visual_helper_source_keys_invalid",
        );
      } catch (error) {
        if (error instanceof HelperError) throw error;
        fail("rhwp_visual_helper_page_query_failed");
      }
      const width = normalizeNumber(layer?.pageWidth, "rhwp_visual_helper_page_size_invalid");
      const height = normalizeNumber(layer?.pageHeight, "rhwp_visual_helper_page_size_invalid");
      if (width <= 0 || height <= 0 || width > MAX_PAGE_DIMENSION || height > MAX_PAGE_DIMENSION) {
        fail("rhwp_visual_helper_page_size_invalid");
      }
      const coordinatePageBBox = layer?.root?.bounds
        ? normalizeBBox(layer.root.bounds, "rhwp_visual_helper_page_size_invalid")
        : { x: 0, y: 0, w: width, h: height };
      if (
        Math.abs(coordinatePageBBox.w - width) > BBOX_TOLERANCE_PX ||
        Math.abs(coordinatePageBBox.h - height) > BBOX_TOLERANCE_PX
      ) {
        fail("rhwp_visual_helper_page_size_invalid");
      }
      pageSizes.push({
        page: pageIndex + 1,
        width,
        height,
        coordinate_page_bbox: coordinatePageBBox,
      });
      if (!keyEnvelope || !Array.isArray(keyEnvelope.keys)) {
        fail("rhwp_visual_helper_source_keys_invalid");
      }
      const pageKeys = new Set();
      for (const key of keyEnvelope.keys) {
        if (!validKey(key)) fail("rhwp_visual_helper_source_key_invalid");
        pageKeys.add(key);
        sourceKeys.add(key);
      }
      pageKeySets.push(pageKeys);
      const ops = extractImageOps(layer.root);
      imageOpsTotal += ops.length;
      if (ops.length > 0) pagesWithImageOps += 1;
      if (imageOpsTotal > MAX_OCCURRENCES) fail("rhwp_visual_helper_occurrence_limit_exceeded");
      for (const op of ops) {
        if (op.sourceImageKey !== null) {
          if (!pageKeys.has(op.sourceImageKey)) unresolvedCounts.source_key_not_listed += 1;
          sourceKeys.add(op.sourceImageKey);
          if (!keyMimes.has(op.sourceImageKey)) keyMimes.set(op.sourceImageKey, new Set());
          if (op.mime) keyMimes.get(op.sourceImageKey).add(op.mime);
        } else if (op.inlineBase64 !== null) {
          const bytes = decodeInlineBase64(op.inlineBase64);
          if (bytes === null) {
            unresolvedCounts.inline_bytes_invalid += 1;
          } else {
            const digest = sha256Bytes(bytes);
            if (!inlineAssets.has(digest)) {
              inlineAssets.set(digest, { bytes, mimeHint: op.mime, anchors: [] });
            }
            op.inlineDigest = digest;
          }
        }
      }
      const matches = matchOpsToControls(ops, layout?.controls, tables);
      for (const match of matches) {
        if (match.reason) unresolvedCounts[match.reason] += 1;
      }
      candidatesByPage.push(matches.filter((match) => match.anchor !== null));
    }

    if (sourceKeys.size + inlineAssets.size > MAX_SOURCE_OBJECTS) {
      fail("rhwp_visual_helper_source_object_limit_exceeded");
    }
    const rawAssets = [];
    let totalAssetBytes = 0;
    for (const key of [...sourceKeys].sort((left, right) => left.localeCompare(right, "en"))) {
      let bytes;
      try {
        bytes = Buffer.from(doc.getSourceImageBytes(key));
      } catch {
        fail("rhwp_visual_helper_source_bytes_unavailable");
      }
      if (bytes.length < 1 || bytes.length > MAX_ASSET_BYTES) {
        fail("rhwp_visual_helper_source_asset_size_exceeded");
      }
      totalAssetBytes += bytes.length;
      if (totalAssetBytes > MAX_TOTAL_ASSET_BYTES) {
        fail("rhwp_visual_helper_source_asset_total_exceeded");
      }
      const sniffed = sniffMediaType(bytes);
      const hints = [...(keyMimes.get(key) ?? [])].sort();
      const mediaType = sniffed !== "application/octet-stream" ? sniffed : (hints.length === 1 ? hints[0] : sniffed);
      rawAssets.push({
        identity: `key:${key}`,
        sourceImageKey: key,
        bytes,
        digest: sha256Bytes(bytes),
        mediaType,
        anchors: [],
      });
    }
    for (const [digest, inline] of [...inlineAssets.entries()].sort(([left], [right]) => left.localeCompare(right))) {
      totalAssetBytes += inline.bytes.length;
      if (totalAssetBytes > MAX_TOTAL_ASSET_BYTES) fail("rhwp_visual_helper_source_asset_total_exceeded");
      const sniffed = sniffMediaType(inline.bytes);
      const mediaType = sniffed !== "application/octet-stream"
        ? sniffed
        : normalizeMediaType(inline.mimeHint, sniffed);
      rawAssets.push({
        identity: `inline:${digest}`,
        sourceImageKey: null,
        bytes: inline.bytes,
        digest,
        mediaType,
        anchors: [],
      });
    }
    rawAssets.sort((left, right) => left.identity.localeCompare(right.identity, "en"));
    const assetByKey = new Map();
    const assetByDigest = new Map();
    rawAssets.forEach((asset, ordinal) => {
      asset.sourceOrdinal = ordinal;
      if (asset.sourceImageKey !== null) assetByKey.set(asset.sourceImageKey, asset);
      else assetByDigest.set(asset.digest, asset);
    });

    const occurrences = [];
    for (let pageIndex = 0; pageIndex < candidatesByPage.length; pageIndex += 1) {
      const candidates = candidatesByPage[pageIndex].sort(occurrenceSort);
      for (let sequence = 0; sequence < candidates.length; sequence += 1) {
        const candidate = candidates[sequence];
        const keyedAsset = candidate.op.sourceImageKey === null
          ? null
          : assetByKey.get(candidate.op.sourceImageKey);
        const inlineAsset = candidate.op.inlineDigest
          ? assetByDigest.get(candidate.op.inlineDigest)
          : null;
        if (candidate.op.sourceImageKey !== null && !keyedAsset) {
          fail("rhwp_visual_helper_source_bytes_unavailable");
        }
        const identity = {
          page: pageIndex + 1,
          bbox: candidate.op.bbox,
          sequence,
          source_image_key: candidate.op.sourceImageKey,
          source_anchor: candidate.anchor,
        };
        const renderDigest = sha256Bytes(Buffer.from(canonicalJson(identity), "utf8")).slice(0, 24);
        const row = {
          schema_version: HELPER_SCHEMA_VERSION,
          doc_id: args["doc-id"],
          render_occurrence_key: `rhwp:${pageIndex + 1}:${sequence}:${renderDigest}`,
          page: pageIndex + 1,
          bbox: candidate.op.bbox,
          coordinate_space: COORDINATE_SPACE,
          sequence_in_page: sequence,
          source_image_key: candidate.op.sourceImageKey,
          source_resource_sha256: keyedAsset?.digest ?? null,
          embedded_raw_sha256: inlineAsset?.digest ?? null,
          normalized_rgba_sha256: null,
          match_bbox: inlineAsset ? candidate.op.bbox : null,
          source_anchor: candidate.anchor,
        };
        occurrences.push(row);
        if (keyedAsset) keyedAsset.anchors.push(candidate.anchor);
        if (inlineAsset) inlineAsset.anchors.push(candidate.anchor);
      }
    }

    const sourceObjects = [];
    const sourceAssets = [];
    for (const asset of rawAssets) {
      const extension = extensionFor(asset.mediaType);
      const destination = path.join(assetDir, `${asset.digest}.${extension}`);
      writeContentVerified(destination, asset.bytes, asset.digest, "rhwp_visual_helper_source_asset_existing_mismatch");
      const anchor = uniqueAnchor(asset.anchors);
      sourceObjects.push({
        schema_version: HELPER_SCHEMA_VERSION,
        doc_id: args["doc-id"],
        source_ordinal: asset.sourceOrdinal,
        source_image_key: asset.sourceImageKey,
        source_object_sha256: asset.digest,
        source_object_media_type: asset.mediaType,
        normalized_rgba_sha256: null,
        supported: isSupportedMedia(asset.mediaType),
        source_anchor: anchor,
      });
      sourceAssets.push({
        source_ordinal: asset.sourceOrdinal,
        source_image_key_sha256: asset.sourceImageKey === null
          ? null
          : sha256Bytes(Buffer.from(asset.sourceImageKey, "utf8")),
        source_object_sha256: asset.digest,
        source_object_media_type: asset.mediaType,
        byte_size: asset.bytes.length,
        relpath: safeRelative(privateRoot, destination, "rhwp_visual_helper_source_asset_path_invalid"),
      });
    }

    const pageRenders = await renderAcceptedPages({
      doc,
      canvasModule,
      pageRecords: occurrences,
      pageSizes,
      pageRenderDir,
      privateRoot,
    });
    const unresolvedOccurrences = imageOpsTotal - occurrences.length;
    const envelope = {
      schema_version: HELPER_SCHEMA_VERSION,
      helper: "rhwp_visual_helper",
      doc_id: args["doc-id"],
      source_sha256: args["source-sha256"],
      dependency_pins: {
        core_js_sha256: args["core-js-sha256"],
        wasm_sha256: args["wasm-sha256"],
        canvas_entry_sha256: args["canvas-sha256"],
      },
      render_profile: {
        profile: RENDER_PROFILE,
        omit_image_bytes: true,
        coordinate_space: COORDINATE_SPACE,
        bbox_match_tolerance_px: BBOX_TOLERANCE_PX,
      },
      occurrences,
      source_objects: sourceObjects,
      source_assets: sourceAssets,
      page_sizes: pageSizes,
      page_renders: pageRenders,
      unresolved: unresolvedCounts,
      counts: {
        page_count: pageCount,
        pages_with_image_ops: pagesWithImageOps,
        image_ops_total: imageOpsTotal,
        placed_occurrences: occurrences.length,
        unresolved_occurrences: unresolvedOccurrences,
        source_objects: sourceObjects.length,
        source_assets: sourceAssets.length,
        unsupported_source_objects: sourceObjects.filter((row) => !row.supported).length,
        page_renders: pageRenders.length,
      },
    };
    const outputBytes = Buffer.from(`${canonicalJson(envelope)}\n`, "utf8");
    if (outputBytes.length > MAX_JSON_RESULT_BYTES) {
      fail("rhwp_visual_helper_output_size_exceeded");
    }
    const outputSha256 = sha256Bytes(outputBytes);
    writeContentVerified(output, outputBytes, outputSha256, "rhwp_visual_helper_output_existing_mismatch");
    process.stdout.write(`${canonicalJson({
      ok: true,
      schema_version: HELPER_SCHEMA_VERSION,
      doc_id: args["doc-id"],
      output_sha256: outputSha256,
      counts: envelope.counts,
    })}\n`);
  } finally {
    try {
      doc.free?.();
    } catch {
      // Cleanup failure must not replace the extraction result.
    }
  }
}

try {
  await run();
} catch (error) {
  const code = error instanceof HelperError ? error.code : "rhwp_visual_helper_internal_error";
  process.stderr.write(`${JSON.stringify({ ok: false, error_code: code })}\n`);
  process.exitCode = 1;
}
