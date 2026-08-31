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
const PAGE_RENDERER = "rhwp_core_renderPageSvg+napi_canvas+data_uri_overlay";
const SHA256_RE = /^[0-9a-f]{64}$/;
const DOC_ID_RE = /^doc_[0-9a-f]{24}$/;
const BLOCK_ID_RE = /^block_[0-9a-f]{24}$/;
const MEDIA_TYPE_RE = /^(?:image|application)\/[A-Za-z0-9.+-]+$/;
const SVG_LENGTH_RE = /^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?(?:px)?$/;
const RASTERIZABLE_DATA_IMAGE_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/bmp",
  "image/webp",
]);
const KNOWN_UNSUPPORTED_DATA_IMAGE_TYPES = new Set([
  "image/gif",
  "image/svg+xml",
  "image/tiff",
  "image/wmf",
]);
const SVG_IMAGE_ATTRIBUTES = new Set([
  "x",
  "y",
  "width",
  "height",
  "preserveAspectRatio",
  "href",
  "xlink:href",
]);
const SVG_CLIP_PATH_ATTRIBUTES = new Set(["id", "clipPathUnits"]);
const SVG_CLIP_RECT_ATTRIBUTES = new Set(["x", "y", "width", "height"]);
const SVG_CLIP_ID_RE = /^[A-Za-z_][A-Za-z0-9_.:-]{0,255}$/;
const SVG_FILTER_ATTRIBUTES = new Set(["id"]);
const SVG_COMPONENT_ATTRIBUTES = new Set(["type", "slope", "intercept"]);
const SVG_EFFECT_NUMBER_RE = /^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?$/;
const MAX_EFFECT_PIXELS = 25_000_000;

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
  return RASTERIZABLE_DATA_IMAGE_TYPES.has(mediaType);
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

function decodeXmlAttribute(value) {
  if (typeof value !== "string" || value.length > MAX_METHOD_JSON_BYTES) {
    fail("rhwp_visual_helper_page_svg_image_invalid");
  }
  let invalid = false;
  const decoded = value.replace(
    /&(?:#([0-9]{1,7})|#x([0-9A-Fa-f]{1,6})|amp|quot|apos|lt|gt);/g,
    (entity, decimal, hexadecimal) => {
      if (decimal !== undefined || hexadecimal !== undefined) {
        const codePoint = Number.parseInt(decimal ?? hexadecimal, decimal !== undefined ? 10 : 16);
        if (
          !Number.isSafeInteger(codePoint) ||
          codePoint < 0 ||
          codePoint > 0x10ffff ||
          (codePoint >= 0xd800 && codePoint <= 0xdfff)
        ) {
          invalid = true;
          return "";
        }
        return String.fromCodePoint(codePoint);
      }
      return {
        "&amp;": "&",
        "&quot;": "\"",
        "&apos;": "'",
        "&lt;": "<",
        "&gt;": ">",
      }[entity];
    },
  );
  if (invalid || decoded.includes("&") || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(decoded)) {
    fail("rhwp_visual_helper_page_svg_image_invalid");
  }
  return decoded;
}

function svgTagEnd(svg, start) {
  let quote = null;
  for (let index = start; index < svg.length; index += 1) {
    const character = svg[index];
    if (quote !== null) {
      if (character === quote) quote = null;
      continue;
    }
    if (character === "\"" || character === "'") {
      quote = character;
    } else if (character === ">") {
      return index;
    }
  }
  fail("rhwp_visual_helper_page_svg_image_invalid");
}

function parseSvgStartTag(tag, expectedName) {
  if (!tag.startsWith(`<${expectedName}`) || !tag.endsWith(">")) {
    fail("rhwp_visual_helper_page_svg_image_invalid");
  }
  let body = tag.slice(expectedName.length + 1, -1);
  const selfClosing = /\/\s*$/.test(body);
  if (selfClosing) body = body.replace(/\/\s*$/, "");
  const attributes = new Map();
  let index = 0;
  while (index < body.length) {
    while (index < body.length && /\s/.test(body[index])) index += 1;
    if (index === body.length) break;
    const nameMatch = /^[A-Za-z_][A-Za-z0-9_.:-]*/.exec(body.slice(index));
    if (!nameMatch) fail("rhwp_visual_helper_page_svg_image_invalid");
    const name = nameMatch[0];
    index += name.length;
    while (index < body.length && /\s/.test(body[index])) index += 1;
    if (body[index] !== "=") fail("rhwp_visual_helper_page_svg_image_invalid");
    index += 1;
    while (index < body.length && /\s/.test(body[index])) index += 1;
    const quote = body[index];
    if (quote !== "\"" && quote !== "'") {
      fail("rhwp_visual_helper_page_svg_image_invalid");
    }
    index += 1;
    const valueStart = index;
    while (index < body.length && body[index] !== quote) index += 1;
    if (index >= body.length || attributes.has(name)) {
      fail("rhwp_visual_helper_page_svg_image_invalid");
    }
    attributes.set(name, decodeXmlAttribute(body.slice(valueStart, index)));
    index += 1;
  }
  return { attributes, selfClosing };
}

function svgLength(attributes, name, { positive, defaultValue = null }) {
  const raw = attributes.get(name);
  if (raw === undefined && defaultValue !== null) {
    return normalizeNumber(
      defaultValue,
      "rhwp_visual_helper_page_svg_image_geometry_invalid",
    );
  }
  if (typeof raw !== "string" || !SVG_LENGTH_RE.test(raw)) {
    fail("rhwp_visual_helper_page_svg_image_geometry_invalid");
  }
  const number = Number.parseFloat(raw.endsWith("px") ? raw.slice(0, -2) : raw);
  if (
    !Number.isFinite(number) ||
    (positive && number <= 0) ||
    Math.abs(number) > MAX_PAGE_DIMENSION
  ) {
    fail("rhwp_visual_helper_page_svg_image_geometry_invalid");
  }
  return normalizeNumber(number, "rhwp_visual_helper_page_svg_image_geometry_invalid");
}

function decodeSvgDataImage(attributes) {
  const hrefs = ["href", "xlink:href"].filter((name) => attributes.has(name));
  if (hrefs.length !== 1) fail("rhwp_visual_helper_page_svg_image_data_invalid");
  const uri = attributes.get(hrefs[0]);
  if (typeof uri !== "string" || uri.length > MAX_ASSET_BYTES * 2 + 256) {
    fail("rhwp_visual_helper_page_svg_image_data_invalid");
  }
  const match = /^data:([^;,]+);base64,([A-Za-z0-9+/=\s]+)$/.exec(uri);
  if (!match) fail("rhwp_visual_helper_page_svg_image_data_invalid");
  const mediaType = normalizeMediaType(match[1], null);
  if (
    mediaType === null ||
    (!RASTERIZABLE_DATA_IMAGE_TYPES.has(mediaType) &&
      !KNOWN_UNSUPPORTED_DATA_IMAGE_TYPES.has(mediaType))
  ) {
    fail("rhwp_visual_helper_page_svg_image_media_invalid");
  }
  const bytes = decodeInlineBase64(match[2]);
  if (bytes === null || sniffMediaType(bytes) !== mediaType) {
    fail("rhwp_visual_helper_page_svg_image_data_invalid");
  }
  return {
    bytes,
    mediaType,
    rasterizable: RASTERIZABLE_DATA_IMAGE_TYPES.has(mediaType),
  };
}

function svgViewBox(attributes) {
  const raw = attributes.get("viewBox");
  if (raw === undefined) return null;
  const pieces = raw.trim().split(/[\s,]+/);
  if (pieces.length !== 4 || pieces.some((piece) => !SVG_LENGTH_RE.test(piece))) {
    fail("rhwp_visual_helper_page_svg_viewbox_invalid");
  }
  const values = pieces.map((piece) => Number.parseFloat(piece.replace(/px$/, "")));
  if (
    values.some((value) => !Number.isFinite(value) || Math.abs(value) > MAX_PAGE_DIMENSION) ||
    values[2] <= 0 ||
    values[3] <= 0 ||
    values[2] * values[3] > MAX_PAGE_PIXELS
  ) {
    fail("rhwp_visual_helper_page_svg_viewbox_invalid");
  }
  return values.map((value) =>
    normalizeNumber(value, "rhwp_visual_helper_page_svg_viewbox_invalid"),
  );
}

function intersectSvgRects(left, right) {
  if (left === null) return { ...right };
  const x = Math.max(left.x, right.x);
  const y = Math.max(left.y, right.y);
  const rightEdge = Math.min(left.x + left.width, right.x + right.width);
  const bottomEdge = Math.min(left.y + left.height, right.y + right.height);
  if (rightEdge <= x || bottomEdge <= y) return null;
  return {
    x: normalizeNumber(x, "rhwp_visual_helper_page_svg_image_geometry_invalid"),
    y: normalizeNumber(y, "rhwp_visual_helper_page_svg_image_geometry_invalid"),
    width: normalizeNumber(
      rightEdge - x,
      "rhwp_visual_helper_page_svg_image_geometry_invalid",
    ),
    height: normalizeNumber(
      bottomEdge - y,
      "rhwp_visual_helper_page_svg_image_geometry_invalid",
    ),
  };
}

function mapSvgRect(context, rectangle) {
  return {
    x: normalizeNumber(
      context.translateX + rectangle.x * context.scaleX,
      "rhwp_visual_helper_page_svg_image_geometry_invalid",
    ),
    y: normalizeNumber(
      context.translateY + rectangle.y * context.scaleY,
      "rhwp_visual_helper_page_svg_image_geometry_invalid",
    ),
    width: normalizeNumber(
      rectangle.width * context.scaleX,
      "rhwp_visual_helper_page_svg_image_geometry_invalid",
    ),
    height: normalizeNumber(
      rectangle.height * context.scaleY,
      "rhwp_visual_helper_page_svg_image_geometry_invalid",
    ),
  };
}

function svgViewportContext(attributes, parent) {
  const x = svgLength(attributes, "x", { positive: false, defaultValue: 0 });
  const y = svgLength(attributes, "y", { positive: false, defaultValue: 0 });
  const width = svgLength(attributes, "width", { positive: true });
  const height = svgLength(attributes, "height", { positive: true });
  if (width * height > MAX_PAGE_PIXELS) {
    fail("rhwp_visual_helper_page_svg_image_geometry_invalid");
  }
  const viewportInRoot = mapSvgRect(parent, { x, y, width, height });
  const clip = intersectSvgRects(parent.clip, viewportInRoot);
  if (clip === null) fail("rhwp_visual_helper_page_svg_image_geometry_invalid");

  const viewBox = svgViewBox(attributes);
  let scaleX = 1;
  let scaleY = 1;
  let localTranslateX = x;
  let localTranslateY = y;
  if (viewBox !== null) {
    const [minimumX, minimumY, viewWidth, viewHeight] = viewBox;
    const preserve = (attributes.get("preserveAspectRatio") ?? "xMidYMid meet")
      .trim()
      .replace(/\s+/g, " ");
    if (preserve === "none") {
      scaleX = width / viewWidth;
      scaleY = height / viewHeight;
      localTranslateX = x - minimumX * scaleX;
      localTranslateY = y - minimumY * scaleY;
    } else {
      const match = /^(xMin|xMid|xMax)(YMin|YMid|YMax)(?: (meet|slice))?$/.exec(preserve);
      if (!match) fail("rhwp_visual_helper_page_svg_preserve_aspect_ratio_invalid");
      const mode = match[3] ?? "meet";
      const scale = mode === "slice"
        ? Math.max(width / viewWidth, height / viewHeight)
        : Math.min(width / viewWidth, height / viewHeight);
      const remainingX = width - viewWidth * scale;
      const remainingY = height - viewHeight * scale;
      const alignX = match[1] === "xMin" ? 0 : match[1] === "xMid" ? 0.5 : 1;
      const alignY = match[2] === "YMin" ? 0 : match[2] === "YMid" ? 0.5 : 1;
      scaleX = scale;
      scaleY = scale;
      localTranslateX = x + remainingX * alignX - minimumX * scale;
      localTranslateY = y + remainingY * alignY - minimumY * scale;
    }
  }
  return {
    scaleX: normalizeNumber(
      parent.scaleX * scaleX,
      "rhwp_visual_helper_page_svg_image_geometry_invalid",
    ),
    scaleY: normalizeNumber(
      parent.scaleY * scaleY,
      "rhwp_visual_helper_page_svg_image_geometry_invalid",
    ),
    translateX: normalizeNumber(
      parent.translateX + parent.scaleX * localTranslateX,
      "rhwp_visual_helper_page_svg_image_geometry_invalid",
    ),
    translateY: normalizeNumber(
      parent.translateY + parent.scaleY * localTranslateY,
      "rhwp_visual_helper_page_svg_image_geometry_invalid",
    ),
    clip,
    opacity: parent.opacity,
    componentTransfer: parent.componentTransfer,
  };
}

function svgOverlayGeometry(context, rectangle) {
  const destination = mapSvgRect(context, rectangle);
  const clipped = intersectSvgRects(context.clip, destination);
  if (clipped === null) fail("rhwp_visual_helper_page_svg_image_geometry_invalid");
  const source = {
    x: (clipped.x - destination.x) / destination.width,
    y: (clipped.y - destination.y) / destination.height,
    width: clipped.width / destination.width,
    height: clipped.height / destination.height,
  };
  for (const value of Object.values(source)) {
    if (!Number.isFinite(value) || value < -1e-9 || value > 1 + 1e-9) {
      fail("rhwp_visual_helper_page_svg_image_geometry_invalid");
    }
  }
  return {
    destination: clipped,
    source: {
      x: Math.max(0, Math.min(1, source.x)),
      y: Math.max(0, Math.min(1, source.y)),
      width: Math.max(0, Math.min(1, source.width)),
      height: Math.max(0, Math.min(1, source.height)),
    },
  };
}

function extractSvgRectClipPaths(svg) {
  const clipPaths = new Map();
  const pattern = /<clipPath(?=[\s>])[^>]*>[\s\S]*?<\/clipPath\s*>/g;
  let matched = 0;
  for (let match = pattern.exec(svg); match !== null; match = pattern.exec(svg)) {
    matched += 1;
    if (matched > MAX_OCCURRENCES) {
      fail("rhwp_visual_helper_page_svg_clip_limit_exceeded");
    }
    const block = match[0];
    const startEnd = svgTagEnd(block, "<clipPath".length);
    const startTag = block.slice(0, startEnd + 1);
    const { attributes, selfClosing } = parseSvgStartTag(startTag, "clipPath");
    if (
      selfClosing ||
      [...attributes.keys()].some((name) => !SVG_CLIP_PATH_ATTRIBUTES.has(name)) ||
      (attributes.get("clipPathUnits") ?? "userSpaceOnUse") !== "userSpaceOnUse"
    ) {
      fail("rhwp_visual_helper_page_svg_clip_unsupported");
    }
    const identifier = attributes.get("id");
    if (typeof identifier !== "string" || !SVG_CLIP_ID_RE.test(identifier)) {
      fail("rhwp_visual_helper_page_svg_clip_invalid");
    }
    const closingStart = block.search(/<\/clipPath\s*>$/);
    if (closingStart < 0) fail("rhwp_visual_helper_page_svg_clip_invalid");
    const body = block.slice(startEnd + 1, closingStart).trim();
    if (!/^<rect(?=[\s>])[\s\S]*\/\s*>$/.test(body)) {
      fail("rhwp_visual_helper_page_svg_clip_unsupported");
    }
    const { attributes: rectAttributes, selfClosing: rectSelfClosing } =
      parseSvgStartTag(body, "rect");
    if (
      !rectSelfClosing ||
      [...rectAttributes.keys()].some((name) => !SVG_CLIP_RECT_ATTRIBUTES.has(name))
    ) {
      fail("rhwp_visual_helper_page_svg_clip_unsupported");
    }
    const rectangle = {
      x: svgLength(rectAttributes, "x", { positive: false, defaultValue: 0 }),
      y: svgLength(rectAttributes, "y", { positive: false, defaultValue: 0 }),
      width: svgLength(rectAttributes, "width", { positive: true }),
      height: svgLength(rectAttributes, "height", { positive: true }),
    };
    if (rectangle.width * rectangle.height > MAX_PAGE_PIXELS || clipPaths.has(identifier)) {
      fail("rhwp_visual_helper_page_svg_clip_invalid");
    }
    clipPaths.set(identifier, rectangle);
  }
  const withoutSupportedClips = svg.replace(pattern, "");
  if (/<\/?clipPath(?=[\s>])/i.test(withoutSupportedClips)) {
    fail("rhwp_visual_helper_page_svg_clip_unsupported");
  }
  return clipPaths;
}

function svgEffectNumber(raw, { minimum, maximum, code }) {
  if (typeof raw !== "string" || !SVG_EFFECT_NUMBER_RE.test(raw)) fail(code);
  const value = Number.parseFloat(raw);
  if (!Number.isFinite(value) || value < minimum || value > maximum) fail(code);
  return normalizeNumber(value, code);
}

function extractSvgComponentTransferFilters(svg) {
  const filters = new Map();
  const pattern = /<filter(?=[\s>])[^>]*>[\s\S]*?<\/filter\s*>/g;
  let matched = 0;
  for (let match = pattern.exec(svg); match !== null; match = pattern.exec(svg)) {
    matched += 1;
    if (matched > MAX_OCCURRENCES) {
      fail("rhwp_visual_helper_page_svg_filter_limit_exceeded");
    }
    const block = match[0];
    const startEnd = svgTagEnd(block, "<filter".length);
    const startTag = block.slice(0, startEnd + 1);
    const { attributes, selfClosing } = parseSvgStartTag(startTag, "filter");
    const identifier = attributes.get("id");
    if (
      selfClosing ||
      [...attributes.keys()].some((name) => !SVG_FILTER_ATTRIBUTES.has(name)) ||
      typeof identifier !== "string" ||
      !SVG_CLIP_ID_RE.test(identifier) ||
      filters.has(identifier)
    ) {
      fail("rhwp_visual_helper_page_svg_filter_invalid");
    }
    const closingStart = block.search(/<\/filter\s*>$/);
    if (closingStart < 0) fail("rhwp_visual_helper_page_svg_filter_invalid");
    const body = block.slice(startEnd + 1, closingStart).trim();
    const componentMatch = /^<feComponentTransfer\s*>([\s\S]*?)<\/feComponentTransfer\s*>$/.exec(body);
    if (componentMatch === null) fail("rhwp_visual_helper_page_svg_filter_structure_unsupported");
    const channels = {};
    const channelPattern = /<feFunc([RGB])(?=[\s>])[^>]*\/\s*>/g;
    for (
      let channelMatch = channelPattern.exec(componentMatch[1]);
      channelMatch !== null;
      channelMatch = channelPattern.exec(componentMatch[1])
    ) {
      const channel = channelMatch[1];
      const tag = channelMatch[0];
      const { attributes: channelAttributes, selfClosing: channelSelfClosing } =
        parseSvgStartTag(tag, `feFunc${channel}`);
      if (
        !channelSelfClosing ||
        Object.hasOwn(channels, channel) ||
        [...channelAttributes.keys()].some((name) => !SVG_COMPONENT_ATTRIBUTES.has(name)) ||
        channelAttributes.get("type") !== "linear"
      ) {
        fail("rhwp_visual_helper_page_svg_filter_channel_unsupported");
      }
      channels[channel] = {
        slope: svgEffectNumber(channelAttributes.get("slope"), {
          minimum: 0,
          maximum: 4,
          code: "rhwp_visual_helper_page_svg_filter_invalid",
        }),
        intercept: svgEffectNumber(channelAttributes.get("intercept"), {
          minimum: -1,
          maximum: 1,
          code: "rhwp_visual_helper_page_svg_filter_invalid",
        }),
      };
    }
    if (Object.keys(channels).sort().join("") !== "BGR") {
      fail("rhwp_visual_helper_page_svg_filter_channel_coverage_unsupported");
    }
    if (componentMatch[1].replace(channelPattern, "").trim() !== "") {
      fail("rhwp_visual_helper_page_svg_filter_content_unsupported");
    }
    filters.set(identifier, channels);
  }
  const withoutSupportedFilters = svg.replace(pattern, "");
  if (/<\/?filter(?=[\s>])/i.test(withoutSupportedFilters)) {
    fail("rhwp_visual_helper_page_svg_filter_definition_unsupported");
  }
  return filters;
}

function svgReferencedClip(tag, name, context, clipPaths) {
  if (!/\sclip-path\s*=/.test(tag)) return context;
  if (name === "svg" || name === "image") {
    fail("rhwp_visual_helper_page_svg_clip_unsupported");
  }
  const { attributes } = parseSvgStartTag(tag, name);
  const reference = attributes.get("clip-path");
  const match = typeof reference === "string" ? /^url\(#([A-Za-z_][A-Za-z0-9_.:-]{0,255})\)$/.exec(reference) : null;
  if (match === null || !clipPaths.has(match[1])) {
    fail("rhwp_visual_helper_page_svg_clip_invalid");
  }
  const clip = intersectSvgRects(context.clip, mapSvgRect(context, clipPaths.get(match[1])));
  if (clip === null) fail("rhwp_visual_helper_page_svg_clip_empty");
  return { ...context, clip };
}

function svgReferencedEffects(tag, name, context, filters) {
  if (!/\s(?:filter|opacity)\s*=/.test(tag)) return context;
  if (name === "svg" || name === "image") {
    fail("rhwp_visual_helper_page_svg_effect_unsupported");
  }
  const { attributes } = parseSvgStartTag(tag, name);
  let opacity = context.opacity;
  if (attributes.has("opacity")) {
    opacity *= svgEffectNumber(attributes.get("opacity"), {
      minimum: 0,
      maximum: 1,
      code: "rhwp_visual_helper_page_svg_effect_invalid",
    });
  }
  let componentTransfer = context.componentTransfer;
  if (attributes.has("filter")) {
    const reference = attributes.get("filter");
    const match = typeof reference === "string"
      ? /^url\(#([A-Za-z_][A-Za-z0-9_.:-]{0,255})\)$/.exec(reference)
      : null;
    if (match === null) fail("rhwp_visual_helper_page_svg_filter_reference_invalid");
    if (!filters.has(match[1])) fail("rhwp_visual_helper_page_svg_filter_reference_missing");
    if (componentTransfer !== null) fail("rhwp_visual_helper_page_svg_filter_nested_unsupported");
    componentTransfer = filters.get(match[1]);
  }
  return {
    ...context,
    opacity: normalizeNumber(opacity, "rhwp_visual_helper_page_svg_effect_invalid"),
    componentTransfer,
  };
}

function extractSvgDataImages(svg) {
  if (
    /<(?:[A-Za-z_][A-Za-z0-9_.-]*:)?style(?=[\s/>])/i.test(svg) ||
    /\sclass\s*=/i.test(svg)
  ) {
    fail("rhwp_visual_helper_page_svg_effect_unsupported");
  }
  if (
    svg.includes("<!--") ||
    svg.includes("<![CDATA[") ||
    /<!DOCTYPE/i.test(svg) ||
    /<(?:script|foreignObject|iframe|object)(?=[\s/>])/i.test(svg) ||
    (/<(?:[A-Za-z_][A-Za-z0-9_.-]*:)?image(?=[\s/>])/i.test(svg) &&
      !/<image(?=[\s/>])/.test(svg))
  ) {
    fail("rhwp_visual_helper_page_svg_image_invalid");
  }
  const overlays = [];
  const clipPaths = extractSvgRectClipPaths(svg);
  const filters = extractSvgComponentTransferFilters(svg);
  const fragments = [];
  let cursor = 0;
  let totalBytes = 0;
  const identity = {
    scaleX: 1,
    scaleY: 1,
    translateX: 0,
    translateY: 0,
    clip: null,
    opacity: 1,
    componentTransfer: null,
  };
  const stack = [];
  const open = /<(\/)?([A-Za-z_][A-Za-z0-9_.:-]*)(?=[\s/>])/g;
  for (let match = open.exec(svg); match !== null; match = open.exec(svg)) {
    const closing = match[1] === "/";
    const name = match[2];
    const end = svgTagEnd(svg, match.index + match[0].length);
    const tag = svg.slice(match.index, end + 1);
    if (closing) {
      while (stack.length > 0) {
        const frame = stack.pop();
        if (frame.name === name) break;
      }
      open.lastIndex = end + 1;
      continue;
    }
    const selfClosing = /\/\s*>$/.test(tag);
    const parent = stack.length > 0
      ? stack[stack.length - 1]
      : { context: identity, transformed: false, effectUnsupported: false };
    const transformed = parent.transformed || /\stransform\s*=/.test(tag);
    const effectUnsupported =
      parent.effectUnsupported ||
      /\s(?:display|mask|overflow|style|visibility)\s*=/.test(tag);
    let context = parent.context;
    if (name === "svg") {
      const parsed = parseSvgStartTag(tag, "svg");
      context = svgViewportContext(parsed.attributes, parent.context);
    }
    context = svgReferencedClip(tag, name, context, clipPaths);
    context = svgReferencedEffects(tag, name, context, filters);
    if (name !== "image") {
      if (!selfClosing) stack.push({ name, context, transformed, effectUnsupported });
      open.lastIndex = end + 1;
      continue;
    }
    if (transformed) {
      fail("rhwp_visual_helper_page_svg_image_transform_unsupported");
    }
    if (effectUnsupported) fail("rhwp_visual_helper_page_svg_effect_unsupported");
    if (stack.some((frame) => frame.name !== "svg" && frame.name !== "g")) {
      fail("rhwp_visual_helper_page_svg_image_structure_unsupported");
    }
    if (match.index < cursor) fail("rhwp_visual_helper_page_svg_image_invalid");
    const { attributes } = parseSvgStartTag(tag, "image");
    let removeEnd = end + 1;
    if (!selfClosing) {
      const closing = /^\s*<\/image\s*>/.exec(svg.slice(removeEnd));
      if (!closing) fail("rhwp_visual_helper_page_svg_image_invalid");
      removeEnd += closing[0].length;
    }
    const x = svgLength(attributes, "x", { positive: false, defaultValue: 0 });
    const y = svgLength(attributes, "y", { positive: false, defaultValue: 0 });
    const width = svgLength(attributes, "width", { positive: true });
    const height = svgLength(attributes, "height", { positive: true });
    if (
      [...attributes.keys()].some((name) => !SVG_IMAGE_ATTRIBUTES.has(name)) ||
      attributes.get("preserveAspectRatio") !== "none"
    ) {
      fail("rhwp_visual_helper_page_svg_image_transform_unsupported");
    }
    if (width * height > MAX_PAGE_PIXELS) {
      fail("rhwp_visual_helper_page_svg_image_geometry_invalid");
    }
    const decoded = decodeSvgDataImage(attributes);
    totalBytes += decoded.bytes.length;
    if (totalBytes > MAX_TOTAL_ASSET_BYTES || overlays.length >= MAX_OCCURRENCES) {
      fail("rhwp_visual_helper_page_svg_image_limit_exceeded");
    }
    fragments.push(svg.slice(cursor, match.index));
    cursor = removeEnd;
    overlays.push({
      ...svgOverlayGeometry(context, { x, y, width, height }),
      opacity: context.opacity,
      componentTransfer: context.componentTransfer,
      ...decoded,
    });
    open.lastIndex = removeEnd;
  }
  fragments.push(svg.slice(cursor));
  const baseSvg = fragments.join("");
  if (/<\/?(?:[A-Za-z_][A-Za-z0-9_.-]*:)?image(?=[\s>])/i.test(baseSvg)) {
    fail("rhwp_visual_helper_page_svg_image_invalid");
  }
  return { baseSvg, overlays };
}

function applySvgOverlayEffects(canvasModule, image, overlay) {
  if (overlay.opacity === 1 && overlay.componentTransfer === null) return image;
  const width = image.width;
  const height = image.height;
  if (
    !Number.isSafeInteger(width) ||
    !Number.isSafeInteger(height) ||
    width < 1 ||
    height < 1 ||
    width * height > MAX_EFFECT_PIXELS
  ) {
    fail("rhwp_visual_helper_page_svg_effect_dimensions_invalid");
  }
  const effectCanvas = canvasModule.createCanvas(width, height);
  const effectContext = effectCanvas.getContext("2d");
  if (
    typeof effectContext.getImageData !== "function" ||
    typeof effectContext.putImageData !== "function"
  ) {
    fail("rhwp_visual_helper_page_svg_effect_contract_invalid");
  }
  effectContext.clearRect?.(0, 0, width, height);
  effectContext.drawImage(image, 0, 0, width, height);
  const imageData = effectContext.getImageData(0, 0, width, height);
  const pixels = imageData?.data;
  if (!(pixels instanceof Uint8ClampedArray) || pixels.length !== width * height * 4) {
    fail("rhwp_visual_helper_page_svg_effect_contract_invalid");
  }
  const channels = overlay.componentTransfer;
  for (let index = 0; index < pixels.length; index += 4) {
    if (channels !== null) {
      for (const [offset, channel] of [[0, "R"], [1, "G"], [2, "B"]]) {
        const transfer = channels[channel];
        const value = (transfer.slope * (pixels[index + offset] / 255) + transfer.intercept) * 255;
        pixels[index + offset] = Math.max(0, Math.min(255, Math.round(value)));
      }
    }
    pixels[index + 3] = Math.max(
      0,
      Math.min(255, Math.round(pixels[index + 3] * overlay.opacity)),
    );
  }
  effectContext.putImageData(imageData, 0, 0);
  return effectCanvas;
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
      const { baseSvg, overlays } = extractSvgDataImages(svg);
      const image = await canvasModule.loadImage(Buffer.from(baseSvg, "utf8"));
      const canvas = canvasModule.createCanvas(pixelWidth, pixelHeight);
      const context = canvas.getContext("2d");
      context.clearRect?.(0, 0, pixelWidth, pixelHeight);
      context.drawImage(image, 0, 0, pixelWidth, pixelHeight);
      const pageBox = size.coordinate_page_bbox;
      const scaleX = pixelWidth / pageBox.w;
      const scaleY = pixelHeight / pageBox.h;
      for (const overlay of overlays) {
        if (!overlay.rasterizable) continue;
        const decodedOverlayImage = await canvasModule.loadImage(overlay.bytes);
        const overlayImage = applySvgOverlayEffects(
          canvasModule,
          decodedOverlayImage,
          overlay,
        );
        const destination = overlay.destination;
        const source = overlay.source;
        const sourceIsComplete =
          Math.abs(source.x) <= 1e-12 &&
          Math.abs(source.y) <= 1e-12 &&
          Math.abs(source.width - 1) <= 1e-12 &&
          Math.abs(source.height - 1) <= 1e-12;
        if (sourceIsComplete) {
          context.drawImage(
            overlayImage,
            (destination.x - pageBox.x) * scaleX,
            (destination.y - pageBox.y) * scaleY,
            destination.width * scaleX,
            destination.height * scaleY,
          );
        } else {
          const sourceWidth = overlayImage.width;
          const sourceHeight = overlayImage.height;
          if (
            !Number.isFinite(sourceWidth) ||
            !Number.isFinite(sourceHeight) ||
            sourceWidth <= 0 ||
            sourceHeight <= 0
          ) {
            fail("rhwp_visual_helper_page_svg_image_dimensions_invalid");
          }
          context.drawImage(
            overlayImage,
            source.x * sourceWidth,
            source.y * sourceHeight,
            source.width * sourceWidth,
            source.height * sourceHeight,
            (destination.x - pageBox.x) * scaleX,
            (destination.y - pageBox.y) * scaleY,
            destination.width * scaleX,
            destination.height * scaleY,
          );
        }
      }
      png = Buffer.from(canvas.toBuffer("image/png"));
    } catch (error) {
      if (error instanceof HelperError) throw error;
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
        renderer: PAGE_RENDERER,
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
