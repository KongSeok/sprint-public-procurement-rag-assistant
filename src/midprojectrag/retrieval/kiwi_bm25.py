"""Independent Korean morphological BM25 lane; no dense candidate dependency."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path
import unicodedata
from weakref import WeakKeyDictionary

from midprojectrag.evidence import EvidenceStore
from midprojectrag.evidence.artifacts import file_sha, private_path, write_new_json
from .contracts import Candidate, SearchResult, freeze, thaw, validate_search

try:  # Capture runtime handles before application-level monkeypatching.
    import kiwipiepy_model as _PINNED_KIWI_MODEL_MODULE
    from kiwipiepy import Kiwi as _PINNED_KIWI_CLASS

    _PINNED_KIWI_MODEL_PATH = _PINNED_KIWI_MODEL_MODULE.get_model_path
    _PINNED_KIWI_VERSION = version("kiwipiepy")
    _PINNED_KIWI_MODEL_VERSION = version("kiwipiepy_model")
except (ImportError, PackageNotFoundError):
    _PINNED_KIWI_CLASS = None
    _PINNED_KIWI_MODEL_PATH = None
    _PINNED_KIWI_VERSION = None
    _PINNED_KIWI_MODEL_VERSION = None


_LOADED_LEXICAL_ATTESTATION = object()
_LOADED_LEXICAL: WeakKeyDictionary = WeakKeyDictionary()
_LOADED_LEXICAL_RUNTIME: WeakKeyDictionary = WeakKeyDictionary()
_TOKENIZER_ATTESTATION_PROBE = "정보시스템 구축 운영비 100원 API 입찰 공고"


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _row_hash(rows) -> str:
    return _digest([row.evidence_id for row in rows])


def _token_rows_hash(rows) -> str:
    return _digest([list(row) for row in rows])


def _kiwi_runtime_handle_is_pinned() -> bool:
    if (
        _PINNED_KIWI_CLASS is None
        or _PINNED_KIWI_CLASS.__module__ != "kiwipiepy"
        or _PINNED_KIWI_CLASS.__qualname__ != "Kiwi"
        or _PINNED_KIWI_VERSION != "0.23.2"
        or _PINNED_KIWI_MODEL_VERSION != "0.23.0"
    ):
        return False
    mro = _PINNED_KIWI_CLASS.__mro__
    return (
        len(mro) >= 3
        and mro[1].__module__ == "kiwipiepy"
        and mro[1].__qualname__ == "_Kiwi"
    )


@dataclass(frozen=True, slots=True, init=False)
class LoadedLexicalArtifactAttestation:
    """Opaque proof that ``KiwiBM25Lane.load`` verified this lane instance."""

    bundle_sha256: str
    rows_sha256: str
    receipt_sha256: str
    tokens_file_sha256: str
    tokens_content_sha256: str
    tokenizer_identity_sha256: str
    tokenizer_kind: str
    tokenizer_runtime_sha256: str
    config_sha256: str
    attestation_sha256: str

    def __init__(self, payload: dict, *, _token=None):
        if _token is not _LOADED_LEXICAL_ATTESTATION:
            raise TypeError("loaded_lexical_attestation_is_loader_sealed")
        expected = {
            "bundle_sha256", "rows_sha256", "receipt_sha256", "tokens_file_sha256",
            "tokens_content_sha256", "tokenizer_identity_sha256", "tokenizer_kind",
            "tokenizer_runtime_sha256", "config_sha256",
        }
        if type(payload) is not dict or set(payload) != expected:
            raise ValueError("invalid_loaded_lexical_attestation")
        for name in expected:
            value = payload[name]
            if type(value) is not str:
                raise ValueError("invalid_loaded_lexical_attestation")
            if name == "tokenizer_kind":
                if value not in {"synthetic", "real_kiwi"}:
                    raise ValueError("invalid_loaded_lexical_attestation")
            elif name == "tokenizer_runtime_sha256":
                if value and (len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
                    raise ValueError("invalid_loaded_lexical_attestation")
            elif len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("invalid_loaded_lexical_attestation")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "attestation_sha256", _digest(payload))


def _production_tokenizer_runtime_sha256(tokenizer, *, expected_runtime=None) -> str:
    if type(tokenizer) is not KiwiTokenizer:
        raise ValueError("lexical_production_tokenizer_required")
    if "tokenize" in vars(tokenizer):
        raise ValueError("lexical_production_tokenizer_method_override")
    if not _kiwi_runtime_handle_is_pinned() or type(tokenizer._kiwi) is not _PINNED_KIWI_CLASS:
        raise ValueError("lexical_production_kiwi_runtime_required")
    if expected_runtime is not None and tokenizer._kiwi is not expected_runtime:
        raise ValueError("lexical_production_kiwi_runtime_drift")
    identity = thaw(tokenizer.identity)
    if type(identity) is not dict or type(identity.get("tokenizer_sha256")) is not str:
        raise ValueError("lexical_production_tokenizer_identity_invalid")
    claimed = identity.pop("tokenizer_sha256")
    if _digest(identity) != claimed:
        raise ValueError("lexical_production_tokenizer_identity_invalid")
    probe = KiwiTokenizer.tokenize(tokenizer, _TOKENIZER_ATTESTATION_PROBE)
    return _digest({"tokenizer_identity": identity | {"tokenizer_sha256": claimed},
                    "runtime": "kiwipiepy.Kiwi", "probe_tokens": list(probe)})


class KiwiTokenizer:
    def __init__(self, *, user_dictionary: tuple[tuple[str, str, float], ...] = ()):
        if not _kiwi_runtime_handle_is_pinned() or _PINNED_KIWI_MODEL_PATH is None:
            raise RuntimeError("kiwi_dependency_unavailable")
        model_path = Path(_PINNED_KIWI_MODEL_PATH())
        files = {p.name: file_sha(p) for p in sorted(model_path.iterdir())
                 if p.is_file() and p.suffix in {".mdl", ".morph", ".dict", ".txt"}}
        if not {"cong.mdl", "default.dict", "sj.morph"} <= files.keys():
            raise RuntimeError("kiwi_model_files_missing")
        dictionary = tuple(tuple(row) for row in user_dictionary)
        if any(len(row) != 3 or type(row[0]) is not str or not row[0] or type(row[1]) is not str
               or type(row[2]) not in (float, int) or not math.isfinite(row[2]) for row in dictionary):
            raise ValueError("invalid_kiwi_user_dictionary")
        self._kiwi = _PINNED_KIWI_CLASS(num_workers=1, model_path=str(model_path), model_type="cong",
                          integrate_allomorph=True, load_default_dict=True, load_typo_dict=True,
                          load_multi_dict=True, enabled_dialects="standard")
        for word, tag, score in dictionary:
            self._kiwi.add_user_word(word, tag, score)
        raw = {"engine": "kiwi", "kiwi_version": "0.23.2", "model_version": "0.23.0", "model_type": "cong",
               "num_workers": 1, "integrate_allomorph": True, "load_default_dict": True, "load_typo_dict": True,
               "load_multi_dict": True, "enabled_dialects": "standard", "token_policy": "content-pos-nfc-casefold-v1",
               "model_files_sha256": files, "user_dictionary": [list(row) for row in dictionary]}
        self.identity = freeze(raw | {"tokenizer_sha256": _digest(raw)})

    def tokenize(self, text: str) -> tuple[str, ...]:
        return tuple(unicodedata.normalize("NFC", token.form).casefold() for token in self._kiwi.tokenize(text)
                     if token.tag.startswith(("N", "V", "MM", "MAG", "MAJ", "SL", "SH", "SN", "XPN", "XR")))


class KiwiBM25Lane:
    def __init__(self, store: EvidenceStore, tokenizer, token_rows, *, k1=1.5, b=0.75, artifact_sha256=None):
        if type(k1) not in (float, int) or type(b) not in (float, int) or not math.isfinite(k1) or not math.isfinite(b) or k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("invalid_bm25_parameters")
        self.store, self.rows, self.tokenizer = store, store.candidates(), tokenizer
        self.tokens = tuple(tuple(row) for row in token_rows)
        if len(self.tokens) != len(self.rows) or any(type(t) is not str or not t for row in self.tokens for t in row):
            raise ValueError("invalid_lexical_token_rows")
        self.k1, self.b = float(k1), float(b)
        self.tf = tuple(Counter(row) for row in self.tokens)
        self.df = Counter(term for tf in self.tf for term in tf)
        self.avgdl = sum(map(len, self.tokens)) / max(1, len(self.tokens))
        self.artifact_sha256 = artifact_sha256 or _digest([list(row) for row in self.tokens])

    @classmethod
    def build(cls, store, tokenizer, **kwargs):
        return cls(store, tokenizer, [tokenizer.tokenize(e.text) for e in store.candidates()], **kwargs)

    @property
    def loaded_artifact_attestation(self) -> LoadedLexicalArtifactAttestation | None:
        return _LOADED_LEXICAL.get(self)

    def search(self, query, limit, *, allowed_doc_ids=None):
        validate_search(query, limit, allowed_doc_ids)
        indices = [i for i, e in enumerate(self.rows) if allowed_doc_ids is None or e.doc_id in allowed_doc_ids]
        trace = {"lane": "lexical", "engine": "kiwi_bm25", "granularity": "child",
                 "bundle_sha256": self.store.bundle_sha256, "artifact_sha256": self.artifact_sha256,
                 "tokenizer_identity": thaw(self.tokenizer.identity), "requested_k": limit,
                 "scoped_rows": len(indices), "k1": self.k1, "b": self.b}
        if not indices:
            return SearchResult((), trace | {"query_tokens": [], "tokenizer_calls": 0, "empty_scope": True})
        attestation = _LOADED_LEXICAL.get(self)
        if (
            type(attestation) is LoadedLexicalArtifactAttestation
            and attestation.tokenizer_kind == "real_kiwi"
        ):
            require_loaded_lexical_artifact(self, self.store, production=True)
            runtime = _LOADED_LEXICAL_RUNTIME[self]
            exposed_tokens = KiwiTokenizer.tokenize(self.tokenizer, query)
            tokens = KiwiTokenizer.tokenize(runtime["query_tokenizer"], query)
            if exposed_tokens != tokens:
                raise ValueError("lexical_exposed_tokenizer_runtime_drift")
            tokenizer_calls = 2
        else:
            tokens = self.tokenizer.tokenize(query)
            tokenizer_calls = 1
        # Authorization/scope is applied to the scoring population, not only
        # to the rows returned. Excluded documents cannot influence IDF or
        # length normalization for a restricted request.
        scoped_df = Counter(term for i in indices for term in self.tf[i])
        scoped_avgdl = sum(len(self.tokens[i]) for i in indices) / len(indices)
        ranked = []
        for i in indices:
            score = 0.0
            for term in sorted(set(tokens)):
                tf = self.tf[i][term]
                if not tf:
                    continue
                df, total = scoped_df[term], len(indices)
                idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
                denom = tf + self.k1 * (1-self.b + self.b * len(self.tokens[i]) / (scoped_avgdl or 1))
                score += idf * tf * (self.k1+1) / denom
            if score > 0:
                ranked.append((i, score))
        ranked.sort(key=lambda pair: (-pair[1], self.rows[pair[0]].evidence_id))
        candidates = tuple(Candidate(self.rows[i].evidence_id, self.rows[i].doc_id, score, "lexical", rank)
                           for rank, (i, score) in enumerate(ranked[:limit], 1))
        return SearchResult(candidates, trace | {
            "query_tokens": list(tokens), "tokenizer_calls": tokenizer_calls,
            "canonical_runtime_crosscheck": tokenizer_calls == 2,
        })

    def save(self, output_dir: Path, *, data_root: Path) -> dict:
        target = private_path(output_dir, data_root)
        target.mkdir(parents=True, exist_ok=False, mode=0o700)
        payload = [{"evidence_id": e.evidence_id, "tokens": list(tokens)} for e, tokens in zip(self.rows, self.tokens)]
        write_new_json(target / "tokens.json", payload)
        receipt = {"schema_version": "1.0", "engine": "kiwi_bm25", "granularity": "child",
                   "bundle_sha256": self.store.bundle_sha256, "tokenizer_identity": thaw(self.tokenizer.identity),
                   "count": len(self.rows), "k1": self.k1, "b": self.b,
                   "tokens_sha256": file_sha(target / "tokens.json")}
        write_new_json(target / "receipt.json", receipt)
        return receipt

    @classmethod
    def load(cls, store, tokenizer, output_dir: Path, *, data_root: Path):
        target = private_path(output_dir, data_root)
        if any(not (target / name).resolve().is_relative_to(target) for name in ("receipt.json", "tokens.json")):
            raise ValueError("lexical_artifact_symlink_escape")
        receipt = json.loads((target / "receipt.json").read_text())
        expected = {"schema_version": "1.0", "engine": "kiwi_bm25", "granularity": "child",
                    "bundle_sha256": store.bundle_sha256, "tokenizer_identity": thaw(tokenizer.identity),
                    "count": len(store.candidates()), "tokens_sha256": file_sha(target / "tokens.json")}
        if type(receipt) is not dict or set(receipt) != set(expected) | {"k1", "b"} or any(receipt.get(k) != v for k, v in expected.items()):
            raise ValueError("lexical_artifact_identity_mismatch")
        payload = json.loads((target / "tokens.json").read_text())
        if type(payload) is not list or any(type(row) is not dict or set(row) != {"evidence_id", "tokens"}
                                           or type(row["tokens"]) is not list for row in payload):
            raise ValueError("invalid_lexical_artifact_rows")
        if [r["evidence_id"] for r in payload] != [e.evidence_id for e in store.candidates()]:
            raise ValueError("lexical_row_identity_mismatch")
        lane = cls(store, tokenizer, [r["tokens"] for r in payload], k1=receipt["k1"], b=receipt["b"],
                   artifact_sha256=file_sha(target / "receipt.json"))
        tokenizer_kind = "real_kiwi" if type(tokenizer) is KiwiTokenizer else "synthetic"
        tokenizer_runtime = ""
        query_tokenizer = None
        if tokenizer_kind == "real_kiwi":
            _production_tokenizer_runtime_sha256(tokenizer)
            identity = thaw(tokenizer.identity)
            dictionary = tuple(
                tuple(row) for row in identity.get("user_dictionary", [])
            )
            query_tokenizer = KiwiTokenizer(user_dictionary=dictionary)
            if thaw(query_tokenizer.identity) != identity:
                raise ValueError("lexical_sealed_tokenizer_identity_mismatch")
            canonical_rows = tuple(
                KiwiTokenizer.tokenize(query_tokenizer, row.text)
                for row in store.candidates()
            )
            if canonical_rows != lane.tokens:
                raise ValueError("lexical_artifact_tokenizer_replay_mismatch")
            tokenizer_runtime = _production_tokenizer_runtime_sha256(query_tokenizer)
        attestation = LoadedLexicalArtifactAttestation(
            {
                "bundle_sha256": store.bundle_sha256,
                "rows_sha256": _row_hash(store.candidates()),
                "receipt_sha256": lane.artifact_sha256,
                "tokens_file_sha256": receipt["tokens_sha256"],
                "tokens_content_sha256": _token_rows_hash(lane.tokens),
                "tokenizer_identity_sha256": _digest(thaw(tokenizer.identity)),
                "tokenizer_kind": tokenizer_kind,
                "tokenizer_runtime_sha256": tokenizer_runtime,
                "config_sha256": _digest({"k1": lane.k1, "b": lane.b}),
            },
            _token=_LOADED_LEXICAL_ATTESTATION,
        )
        _LOADED_LEXICAL[lane] = attestation
        if tokenizer_kind == "real_kiwi":
            _LOADED_LEXICAL_RUNTIME[lane] = {
                "source_tokenizer": tokenizer,
                "source_runtime": tokenizer._kiwi,
                "query_tokenizer": query_tokenizer,
                "query_runtime": query_tokenizer._kiwi,
            }
        return lane


def require_loaded_lexical_artifact(
    lane: KiwiBM25Lane, store: EvidenceStore, *, production: bool = False
) -> LoadedLexicalArtifactAttestation:
    """Return a loader-issued proof after revalidating token and BM25 state."""

    if type(lane) is not KiwiBM25Lane or type(store) is not EvidenceStore:
        raise ValueError("loaded_lexical_artifact_required")
    attestation = _LOADED_LEXICAL.get(lane)
    if type(attestation) is not LoadedLexicalArtifactAttestation:
        raise ValueError("loaded_lexical_artifact_required")
    rows = store.candidates()
    if lane.store is not store or tuple(lane.rows) != rows:
        raise ValueError("loaded_lexical_store_or_rows_mismatch")
    expected_tf = tuple(Counter(row) for row in lane.tokens)
    expected_df = Counter(term for tf in expected_tf for term in tf)
    expected_avgdl = sum(map(len, lane.tokens)) / max(1, len(lane.tokens))
    if lane.tf != expected_tf or lane.df != expected_df or lane.avgdl != expected_avgdl:
        raise ValueError("loaded_lexical_bm25_state_drift")
    checks = {
        "bundle_sha256": store.bundle_sha256,
        "rows_sha256": _row_hash(rows),
        "receipt_sha256": lane.artifact_sha256,
        "tokens_content_sha256": _token_rows_hash(lane.tokens),
        "tokenizer_identity_sha256": _digest(thaw(lane.tokenizer.identity)),
        "config_sha256": _digest({"k1": lane.k1, "b": lane.b}),
    }
    if any(getattr(attestation, name) != value for name, value in checks.items()):
        raise ValueError("loaded_lexical_runtime_drift")
    if production:
        if attestation.tokenizer_kind != "real_kiwi":
            raise ValueError("loaded_lexical_production_tokenizer_required")
        runtime = _LOADED_LEXICAL_RUNTIME.get(lane)
        if type(runtime) is not dict or set(runtime) != {
            "source_tokenizer", "source_runtime", "query_tokenizer", "query_runtime"
        }:
            raise ValueError("loaded_lexical_runtime_attestation_missing")
        if runtime["source_tokenizer"] is not lane.tokenizer:
            raise ValueError("loaded_lexical_source_tokenizer_drift")
        source_sha = _production_tokenizer_runtime_sha256(
            lane.tokenizer, expected_runtime=runtime["source_runtime"]
        )
        query_sha = _production_tokenizer_runtime_sha256(
            runtime["query_tokenizer"], expected_runtime=runtime["query_runtime"]
        )
        if (
            not attestation.tokenizer_runtime_sha256
            or source_sha != attestation.tokenizer_runtime_sha256
            or query_sha != attestation.tokenizer_runtime_sha256
        ):
            raise ValueError("loaded_lexical_tokenizer_runtime_drift")
    return attestation
