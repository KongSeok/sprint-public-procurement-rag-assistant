"""Independent Korean morphological BM25 lane; no dense candidate dependency."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path
from types import FunctionType, MemberDescriptorType
from typing import NamedTuple
import unicodedata
from weakref import ReferenceType, ref

from midprojectrag.evidence import EvidenceStore, validate_evidence_store_snapshot
from midprojectrag.evidence.artifacts import file_sha, private_path, write_new_json
from .contracts import (
    Candidate,
    RetrievalPostCallContractError,
    RetrievalProviderError,
    SearchResult,
    freeze,
    thaw,
    validate_search,
)

try:  # Capture runtime handles before application-level monkeypatching.
    import kiwipiepy_model as _PINNED_KIWI_MODEL_MODULE
    from kiwipiepy import Kiwi as _PINNED_KIWI_CLASS

    _PINNED_KIWI_MODEL_PATH = _PINNED_KIWI_MODEL_MODULE.get_model_path
    _PINNED_KIWI_VERSION = version("kiwipiepy")
    _PINNED_KIWI_MODEL_VERSION = version("kiwipiepy_model")
    _PINNED_KIWI_RUNTIME_TOKENIZE = type.__getattribute__(
        _PINNED_KIWI_CLASS, "__dict__"
    )["tokenize"]
    _PINNED_KIWI_RUNTIME_TOKENIZE_CODE = object.__getattribute__(
        _PINNED_KIWI_RUNTIME_TOKENIZE, "__code__"
    )
except (ImportError, PackageNotFoundError):
    _PINNED_KIWI_CLASS = None
    _PINNED_KIWI_MODEL_PATH = None
    _PINNED_KIWI_VERSION = None
    _PINNED_KIWI_MODEL_VERSION = None
    _PINNED_KIWI_RUNTIME_TOKENIZE = None
    _PINNED_KIWI_RUNTIME_TOKENIZE_CODE = None


_LOADED_LEXICAL_ATTESTATION = object()
_TOKENIZER_ATTESTATION_PROBE = "정보시스템 구축 운영비 100원 API 입찰 공고"
_LEXICAL_ATTESTATION_FIELDS = (
    "bundle_sha256",
    "rows_sha256",
    "receipt_sha256",
    "tokens_file_sha256",
    "tokens_content_sha256",
    "tokenizer_identity_sha256",
    "tokenizer_kind",
    "tokenizer_runtime_sha256",
    "config_sha256",
)


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
    class_state = type.__getattribute__(_PINNED_KIWI_CLASS, "__dict__")
    runtime_tokenize = class_state.get("tokenize")
    return (
        len(mro) >= 3
        and mro[1].__module__ == "kiwipiepy"
        and mro[1].__qualname__ == "_Kiwi"
        and type(runtime_tokenize) is FunctionType
        and runtime_tokenize is _PINNED_KIWI_RUNTIME_TOKENIZE
        and object.__getattribute__(runtime_tokenize, "__code__")
        is _PINNED_KIWI_RUNTIME_TOKENIZE_CODE
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
        _require_pinned_attestation_descriptors()
        if _token is not _LOADED_LEXICAL_ATTESTATION:
            raise TypeError("loaded_lexical_attestation_is_loader_sealed")
        expected = set(_LEXICAL_ATTESTATION_FIELDS)
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


_PINNED_LEXICAL_ATTESTATION_GETATTRIBUTE = (
    LoadedLexicalArtifactAttestation.__getattribute__
)
_PINNED_LEXICAL_ATTESTATION_DESCRIPTORS = tuple(
    (
        name,
        type.__getattribute__(LoadedLexicalArtifactAttestation, "__dict__")[name],
    )
    for name in _LEXICAL_ATTESTATION_FIELDS + ("attestation_sha256",)
)


def _require_pinned_attestation_descriptors() -> None:
    class_state = type.__getattribute__(
        LoadedLexicalArtifactAttestation, "__dict__"
    )
    if (
        class_state.get("__getattribute__", object.__getattribute__)
        is not _PINNED_LEXICAL_ATTESTATION_GETATTRIBUTE
    ):
        raise ValueError("loaded_lexical_attestation_descriptor_override")
    for name, issued_descriptor in _PINNED_LEXICAL_ATTESTATION_DESCRIPTORS:
        current_descriptor = class_state.get(name)
        if (
            type(current_descriptor) is not MemberDescriptorType
            or current_descriptor is not issued_descriptor
        ):
            raise ValueError("loaded_lexical_attestation_descriptor_override")


def _require_sha256(value: object, code: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(code)
    return value


def _validate_lexical_attestation_snapshot(
    attestation: LoadedLexicalArtifactAttestation,
    issued_payload: tuple[tuple[str, str], ...],
) -> None:
    if type(attestation) is not LoadedLexicalArtifactAttestation:
        raise ValueError("loaded_lexical_artifact_required")
    _require_pinned_attestation_descriptors()
    payload = {}
    for name in _LEXICAL_ATTESTATION_FIELDS:
        value = object.__getattribute__(attestation, name)
        if type(value) is not str:
            raise ValueError("loaded_lexical_attestation_payload_drift")
        if name == "tokenizer_kind":
            if value not in {"synthetic", "real_kiwi"}:
                raise ValueError("loaded_lexical_attestation_payload_drift")
        elif name == "tokenizer_runtime_sha256":
            if value:
                _require_sha256(value, "loaded_lexical_attestation_payload_drift")
        else:
            _require_sha256(value, "loaded_lexical_attestation_payload_drift")
        payload[name] = value
    claimed = object.__getattribute__(attestation, "attestation_sha256")
    _require_sha256(claimed, "loaded_lexical_attestation_payload_drift")
    if claimed != _digest(payload):
        raise ValueError("loaded_lexical_attestation_hash_mismatch")
    if tuple(dict.items(payload)) != issued_payload:
        raise ValueError("loaded_lexical_attestation_issued_payload_drift")


def _require_pinned_tokenize_implementation() -> FunctionType:
    _validate_production_dispatch_dependencies()
    class_state = type.__getattribute__(KiwiTokenizer, "__dict__")
    tokenize = class_state.get("tokenize")
    if (
        type(tokenize) is not FunctionType
        or tokenize is not _PINNED_KIWI_TOKENIZE
        or object.__getattribute__(tokenize, "__code__")
        is not _PINNED_KIWI_TOKENIZE_CODE
        or class_state.get("__getattribute__", object.__getattribute__)
        is not _PINNED_KIWI_TOKENIZER_GETATTRIBUTE
        or class_state.get("__hash__", object.__hash__)
        is not _PINNED_KIWI_TOKENIZER_HASH
    ):
        raise ValueError("lexical_production_tokenizer_method_override")
    return tokenize


def _tokenizer_state(tokenizer: object) -> dict:
    try:
        state = object.__getattribute__(tokenizer, "__dict__")
    except (AttributeError, TypeError) as exc:
        raise ValueError("lexical_production_tokenizer_state_drift") from exc
    if type(state) is not dict:
        raise ValueError("lexical_production_tokenizer_state_drift")
    keys = tuple(dict.keys(state))
    if any(type(key) is not str for key in keys):
        raise ValueError("lexical_production_tokenizer_state_drift")
    return state


def _validate_production_tokenizer_runtime(
    tokenizer: object,
    *,
    expected_runtime: object | None = None,
    expected_identity: object | None = None,
) -> dict:
    """Validate exact Kiwi identities without invoking the tokenizer/model."""

    _validate_production_dispatch_dependencies()
    if type(tokenizer) is not KiwiTokenizer:
        raise ValueError("lexical_production_tokenizer_required")
    _require_pinned_tokenize_implementation()
    state = _tokenizer_state(tokenizer)
    if len(state) != 2 or "_kiwi" not in state or "identity" not in state:
        raise ValueError("lexical_production_tokenizer_state_drift")
    runtime = dict.__getitem__(state, "_kiwi")
    identity_value = dict.__getitem__(state, "identity")
    if (
        not _kiwi_runtime_handle_is_pinned()
        or type(runtime) is not _PINNED_KIWI_CLASS
    ):
        raise ValueError("lexical_production_kiwi_runtime_required")
    if expected_runtime is not None and runtime is not expected_runtime:
        raise ValueError("lexical_production_kiwi_runtime_drift")
    if expected_identity is not None and identity_value is not expected_identity:
        raise ValueError("lexical_production_tokenizer_identity_drift")
    identity = thaw(identity_value)
    if type(identity) is not dict or type(identity.get("tokenizer_sha256")) is not str:
        raise ValueError("lexical_production_tokenizer_identity_invalid")
    claimed = identity.pop("tokenizer_sha256")
    if _digest(identity) != claimed:
        raise ValueError("lexical_production_tokenizer_identity_invalid")
    return identity | {"tokenizer_sha256": claimed}


def _issue_production_tokenizer_runtime_sha256(tokenizer: object) -> str:
    """Mint a runtime receipt; tokenization is allowed only at issuance."""

    _validate_production_dispatch_dependencies()
    identity = _validate_production_tokenizer_runtime(tokenizer)
    tokenize = _require_pinned_tokenize_implementation()
    probe = tokenize(tokenizer, _TOKENIZER_ATTESTATION_PROBE)
    if type(probe) is not tuple or any(type(token) is not str for token in probe):
        raise ValueError("lexical_production_tokenizer_probe_invalid")
    return _digest({"tokenizer_identity": identity,
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
        _validate_production_dispatch_dependencies()
        state = object.__getattribute__(self, "__dict__")
        if type(state) is not dict or "_kiwi" not in state:
            raise ValueError("lexical_production_tokenizer_state_drift")
        runtime = dict.__getitem__(state, "_kiwi")
        if (
            type(runtime) is not _PINNED_KIWI_CLASS
            or not _kiwi_runtime_handle_is_pinned()
        ):
            raise ValueError("lexical_production_kiwi_runtime_required")
        runtime_tokenize = type.__getattribute__(
            _PINNED_KIWI_CLASS, "__dict__"
        ).get("tokenize")
        try:
            raw_tokens = tuple(runtime_tokenize(runtime, text))
        except Exception as exc:
            raise RetrievalProviderError("lexical_provider_error") from exc
        try:
            return tuple(
                unicodedata.normalize("NFC", token.form).casefold()
                for token in raw_tokens
                if token.tag.startswith(
                    ("N", "V", "MM", "MAG", "MAJ", "SL", "SH", "SN", "XPN", "XR")
                )
            )
        except RetrievalPostCallContractError:
            raise
        except Exception as exc:
            raise RetrievalPostCallContractError(
                "lexical_post_call_contract_error"
            ) from exc


_PINNED_KIWI_TOKENIZE = KiwiTokenizer.tokenize
_PINNED_KIWI_TOKENIZE_CODE = object.__getattribute__(
    _PINNED_KIWI_TOKENIZE, "__code__"
)
_PINNED_KIWI_TOKENIZER_GETATTRIBUTE = KiwiTokenizer.__getattribute__
_PINNED_KIWI_TOKENIZER_HASH = KiwiTokenizer.__hash__


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
        _validate_production_dispatch_dependencies()
        if type(tokenizer) is KiwiTokenizer:
            _validate_production_tokenizer_runtime(tokenizer)
            tokenize = _require_pinned_tokenize_implementation()
            token_rows = [
                tokenize(tokenizer, evidence.text)
                for evidence in store.candidates()
            ]
        else:
            token_rows = [
                tokenizer.tokenize(evidence.text) for evidence in store.candidates()
            ]
        return cls(store, tokenizer, token_rows, **kwargs)

    @property
    def loaded_artifact_attestation(self) -> LoadedLexicalArtifactAttestation | None:
        _validate_production_dispatch_dependencies()
        _require_pinned_search_implementation()
        authority = _lookup_loaded_lexical_authority(self)
        return None if authority is None else authority.attestation

    def search(self, query, limit, *, allowed_doc_ids=None):
        _validate_production_dispatch_dependencies()
        _require_pinned_search_implementation()
        validate_search(query, limit, allowed_doc_ids)
        authority = _lookup_loaded_lexical_authority(self)
        if (
            authority is not None
            and object.__getattribute__(authority.attestation, "tokenizer_kind")
            == "real_kiwi"
        ):
            # This performs every identity/code check before row traversal or
            # either of the two actual query-tokenizer calls below.
            require_loaded_lexical_artifact(self, authority.store, production=True)
        state = _read_lane_state(self)
        rows = dict.__getitem__(state, "rows")
        store = dict.__getitem__(state, "store")
        tokenizer = dict.__getitem__(state, "tokenizer")
        indices = [
            index
            for index, evidence in enumerate(rows)
            if allowed_doc_ids is None or evidence.doc_id in allowed_doc_ids
        ]
        trace = {"lane": "lexical", "engine": "kiwi_bm25", "granularity": "child",
                 "bundle_sha256": store.bundle_sha256,
                 "artifact_sha256": dict.__getitem__(state, "artifact_sha256"),
                 "tokenizer_identity": thaw(object.__getattribute__(tokenizer, "identity")),
                 "requested_k": limit, "scoped_rows": len(indices),
                 "k1": dict.__getitem__(state, "k1"),
                 "b": dict.__getitem__(state, "b")}
        if not indices:
            return SearchResult((), trace | {"query_tokens": [], "tokenizer_calls": 0, "empty_scope": True})
        production_tokenizer = (
            authority is not None
            and object.__getattribute__(authority.attestation, "tokenizer_kind")
            == "real_kiwi"
        )
        tokenize = (
            _require_pinned_tokenize_implementation()
            if production_tokenizer
            else None
        )
        try:
            if production_tokenizer:
                exposed_tokens = tokenize(tokenizer, query)
                tokens = tokenize(authority.query_tokenizer, query)
                if exposed_tokens != tokens:
                    raise RetrievalPostCallContractError(
                        "lexical_exposed_tokenizer_runtime_drift"
                    )
                tokenizer_calls = 2
            else:
                tokens = tokenizer.tokenize(query)
                tokenizer_calls = 1
            # Authorization/scope is applied to the scoring population, not only
            # to the rows returned. Excluded documents cannot influence IDF or
            # length normalization for a restricted request.
            tf_rows = dict.__getitem__(state, "tf")
            token_rows = dict.__getitem__(state, "tokens")
            k1 = dict.__getitem__(state, "k1")
            b = dict.__getitem__(state, "b")
            scoped_df = {}
            for index in indices:
                for term, _count in dict.items(tf_rows[index]):
                    dict.__setitem__(
                        scoped_df,
                        term,
                        dict.get(scoped_df, term, 0) + 1,
                    )
            scoped_avgdl = sum(len(token_rows[i]) for i in indices) / len(indices)
            ranked = []
            for i in indices:
                score = 0.0
                for term in sorted(set(tokens)):
                    tf = dict.get(tf_rows[i], term, 0)
                    if not tf:
                        continue
                    df, total = dict.__getitem__(scoped_df, term), len(indices)
                    idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
                    denom = tf + k1 * (1-b + b * len(token_rows[i]) / (scoped_avgdl or 1))
                    score += idf * tf * (k1+1) / denom
                if score > 0:
                    ranked.append((i, score))
            ranked.sort(key=lambda pair: (-pair[1], rows[pair[0]].evidence_id))
            candidates = tuple(Candidate(rows[i].evidence_id, rows[i].doc_id, score, "lexical", rank)
                               for rank, (i, score) in enumerate(ranked[:limit], 1))
            return SearchResult(candidates, trace | {
                "query_tokens": list(tokens), "tokenizer_calls": tokenizer_calls,
                "canonical_runtime_crosscheck": tokenizer_calls == 2,
            })
        except (RetrievalProviderError, RetrievalPostCallContractError):
            raise
        except Exception as exc:
            raise RetrievalPostCallContractError(
                "lexical_post_call_contract_error"
            ) from exc

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
        _validate_production_dispatch_dependencies()
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
            source_runtime_sha256 = _issue_production_tokenizer_runtime_sha256(
                tokenizer
            )
            identity = thaw(object.__getattribute__(tokenizer, "identity"))
            dictionary = tuple(
                tuple(row) for row in identity.get("user_dictionary", [])
            )
            query_tokenizer = KiwiTokenizer(user_dictionary=dictionary)
            if thaw(object.__getattribute__(query_tokenizer, "identity")) != identity:
                raise ValueError("lexical_sealed_tokenizer_identity_mismatch")
            tokenize = _require_pinned_tokenize_implementation()
            canonical_rows = tuple(
                tokenize(query_tokenizer, row.text)
                for row in store.candidates()
            )
            if canonical_rows != lane.tokens:
                raise ValueError("lexical_artifact_tokenizer_replay_mismatch")
            tokenizer_runtime = _issue_production_tokenizer_runtime_sha256(
                query_tokenizer
            )
            if tokenizer_runtime != source_runtime_sha256:
                raise ValueError("lexical_sealed_tokenizer_runtime_mismatch")
        proof_payload = {
            "bundle_sha256": store.bundle_sha256,
            "rows_sha256": _row_hash(store.candidates()),
            "receipt_sha256": lane.artifact_sha256,
            "tokens_file_sha256": receipt["tokens_sha256"],
            "tokens_content_sha256": _token_rows_hash(lane.tokens),
            "tokenizer_identity_sha256": _digest(
                thaw(object.__getattribute__(tokenizer, "identity"))
            ),
            "tokenizer_kind": tokenizer_kind,
            "tokenizer_runtime_sha256": tokenizer_runtime,
            "config_sha256": _digest({"k1": lane.k1, "b": lane.b}),
        }
        attestation = LoadedLexicalArtifactAttestation(
            proof_payload,
            _token=_LOADED_LEXICAL_ATTESTATION,
        )
        _register_loaded_lexical_authority(
            lane=lane,
            attestation=attestation,
            proof_payload=proof_payload,
            query_tokenizer=query_tokenizer,
        )
        return lane


_PINNED_LEXICAL_SEARCH = KiwiBM25Lane.search
_PINNED_LEXICAL_SEARCH_CODE = object.__getattribute__(
    _PINNED_LEXICAL_SEARCH, "__code__"
)
_PINNED_LEXICAL_GETATTRIBUTE = KiwiBM25Lane.__getattribute__
_PINNED_LEXICAL_HASH = KiwiBM25Lane.__hash__
_LEXICAL_LANE_FIELDS = (
    "store",
    "rows",
    "tokenizer",
    "tokens",
    "k1",
    "b",
    "tf",
    "df",
    "avgdl",
    "artifact_sha256",
)


class _LoadedLexicalAuthority(NamedTuple):
    weak: ReferenceType[object]
    attestation: LoadedLexicalArtifactAttestation
    proof_payload: tuple[tuple[str, str], ...]
    bundle_sha256: str
    store: EvidenceStore
    rows: tuple
    tokenizer: object
    tokenizer_type: type
    tokenizer_identity: object
    tokens: tuple
    tf: tuple
    df: Counter
    avgdl: float
    artifact_sha256: str
    k1: float
    b: float
    source_runtime: object | None
    query_tokenizer: object | None
    query_tokenizer_identity: object | None
    query_runtime: object | None


_LOADED_LEXICAL_AUTHORITIES: dict[int, _LoadedLexicalAuthority] = {}
_ISSUED_LOADED_LEXICAL_AUTHORITIES = _LOADED_LEXICAL_AUTHORITIES
_LOADED_LEXICAL_AUTHORITY_SIZE = 20


def _drop_loaded_lexical_authority(
    identity: int, dead: ReferenceType[object]
) -> None:
    current = dict.get(_ISSUED_LOADED_LEXICAL_AUTHORITIES, identity)
    if (
        type(current) is _LoadedLexicalAuthority
        and tuple.__len__(current) == _LOADED_LEXICAL_AUTHORITY_SIZE
        and type(tuple.__getitem__(current, 0)) is ReferenceType
        and tuple.__getitem__(current, 0) is dead
    ):
        dict.pop(_ISSUED_LOADED_LEXICAL_AUTHORITIES, identity, None)


def _lookup_loaded_lexical_authority(
    lane: object,
) -> _LoadedLexicalAuthority | None:
    authority = dict.get(_ISSUED_LOADED_LEXICAL_AUTHORITIES, id(lane))
    if authority is None:
        return None
    if (
        type(authority) is not _LoadedLexicalAuthority
        or tuple.__len__(authority) != _LOADED_LEXICAL_AUTHORITY_SIZE
    ):
        raise ValueError("loaded_lexical_authority_registry_drift")
    weak = tuple.__getitem__(authority, 0)
    if type(weak) is not ReferenceType:
        raise ValueError("loaded_lexical_authority_registry_drift")
    if weak() is not lane:
        return None
    return authority


def _require_pinned_search_implementation() -> None:
    _validate_production_dispatch_dependencies()
    _require_pinned_attestation_descriptors()
    class_state = type.__getattribute__(KiwiBM25Lane, "__dict__")
    search = class_state.get("search")
    if (
        type(search) is not FunctionType
        or search is not _PINNED_LEXICAL_SEARCH
        or object.__getattribute__(search, "__code__")
        is not _PINNED_LEXICAL_SEARCH_CODE
        or class_state.get("__getattribute__", object.__getattribute__)
        is not _PINNED_LEXICAL_GETATTRIBUTE
        or class_state.get("__hash__", object.__hash__)
        is not _PINNED_LEXICAL_HASH
    ):
        raise ValueError("loaded_lexical_search_method_override")
    _require_pinned_tokenize_implementation()


def _read_lane_state(lane: KiwiBM25Lane) -> dict:
    try:
        state = object.__getattribute__(lane, "__dict__")
    except (AttributeError, TypeError) as exc:
        raise ValueError("loaded_lexical_snapshot_type_drift") from exc
    if type(state) is not dict:
        raise ValueError("loaded_lexical_snapshot_type_drift")
    keys = tuple(dict.keys(state))
    if (
        any(type(key) is not str for key in keys)
        or len(keys) != len(_LEXICAL_LANE_FIELDS)
        or any(name not in state for name in _LEXICAL_LANE_FIELDS)
    ):
        raise ValueError("loaded_lexical_snapshot_type_drift")
    return state


def _counter_snapshot(counter: object) -> tuple[tuple[str, int], ...]:
    if type(counter) is not Counter:
        raise ValueError("loaded_lexical_snapshot_type_drift")
    items = []
    for key, value in dict.items(counter):
        if type(key) is not str or type(value) is not int:
            raise ValueError("loaded_lexical_snapshot_type_drift")
        items.append((key, value))
    return tuple(sorted(items))


def _token_count_snapshot(tokens: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
    counts = {}
    for token in tokens:
        dict.__setitem__(counts, token, dict.get(counts, token, 0) + 1)
    return tuple(sorted(dict.items(counts)))


def _register_loaded_lexical_authority(
    *,
    lane: KiwiBM25Lane,
    attestation: LoadedLexicalArtifactAttestation,
    proof_payload: dict,
    query_tokenizer: KiwiTokenizer | None,
) -> None:
    _validate_production_dispatch_dependencies()
    _require_pinned_search_implementation()
    state = _read_lane_state(lane)
    store = dict.__getitem__(state, "store")
    rows = dict.__getitem__(state, "rows")
    tokenizer = dict.__getitem__(state, "tokenizer")
    tokenizer_identity = object.__getattribute__(tokenizer, "identity")
    source_runtime = None
    query_identity = None
    query_runtime = None
    if type(tokenizer) is KiwiTokenizer:
        _validate_production_tokenizer_runtime(
            tokenizer, expected_identity=tokenizer_identity
        )
        source_runtime = dict.__getitem__(_tokenizer_state(tokenizer), "_kiwi")
        if type(query_tokenizer) is not KiwiTokenizer:
            raise ValueError("lexical_sealed_tokenizer_runtime_missing")
        query_identity = object.__getattribute__(query_tokenizer, "identity")
        _validate_production_tokenizer_runtime(
            query_tokenizer, expected_identity=query_identity
        )
        query_runtime = dict.__getitem__(
            _tokenizer_state(query_tokenizer), "_kiwi"
        )
    elif query_tokenizer is not None:
        raise ValueError("lexical_synthetic_query_tokenizer_forbidden")
    issued_payload = tuple(
        (name, dict.__getitem__(proof_payload, name))
        for name in _LEXICAL_ATTESTATION_FIELDS
    )
    identity = id(lane)
    weak = ref(
        lane,
        lambda dead, identity=identity: _drop_loaded_lexical_authority(
            identity, dead
        ),
    )
    authority = _LoadedLexicalAuthority(
        weak=weak,
        attestation=attestation,
        proof_payload=issued_payload,
        bundle_sha256=dict.__getitem__(proof_payload, "bundle_sha256"),
        store=store,
        rows=rows,
        tokenizer=tokenizer,
        tokenizer_type=type(tokenizer),
        tokenizer_identity=tokenizer_identity,
        tokens=dict.__getitem__(state, "tokens"),
        tf=dict.__getitem__(state, "tf"),
        df=dict.__getitem__(state, "df"),
        avgdl=dict.__getitem__(state, "avgdl"),
        artifact_sha256=dict.__getitem__(state, "artifact_sha256"),
        k1=dict.__getitem__(state, "k1"),
        b=dict.__getitem__(state, "b"),
        source_runtime=source_runtime,
        query_tokenizer=query_tokenizer,
        query_tokenizer_identity=query_identity,
        query_runtime=query_runtime,
    )
    dict.__setitem__(_ISSUED_LOADED_LEXICAL_AUTHORITIES, identity, authority)


def preflight_loaded_lexical_artifact(
    lane: KiwiBM25Lane,
    store: EvidenceStore,
    *,
    _dependency_checker=None,
    _dependency_checker_code=None,
    _dependency_checker_defaults=None,
    _dependency_checker_globals=None,
) -> LoadedLexicalArtifactAttestation:
    """Validate loader authority without store traversal or tokenizer calls."""

    module_globals = globals()
    if (
        _dependency_checker_globals is not module_globals
        or _dependency_checker_globals
        is not dict.get(module_globals, "_PRODUCTION_DISPATCH_GLOBALS")
        or _dependency_checker
        is not dict.get(
            module_globals,
            "_ISSUED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER",
        )
        or _dependency_checker
        is not dict.get(
            module_globals, "_validate_production_dispatch_dependencies"
        )
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(
            module_globals,
            "_PINNED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER_CODE",
        )
        or object.__getattribute__(_dependency_checker, "__globals__")
        is not module_globals
        or object.__getattribute__(_dependency_checker, "__defaults__")
        is not _dependency_checker_defaults
        or _dependency_checker_defaults
        is not dict.get(
            module_globals,
            "_PINNED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER_DEFAULTS",
        )
    ):
        raise ValueError("lexical_production_dispatch_dependency_drift")
    _dependency_checker()
    if type(lane) is not KiwiBM25Lane or type(store) is not EvidenceStore:
        raise ValueError("loaded_lexical_artifact_required")
    _require_pinned_search_implementation()
    authority = _lookup_loaded_lexical_authority(lane)
    if authority is None:
        raise ValueError("loaded_lexical_artifact_required")
    state = _read_lane_state(lane)
    current_store = dict.__getitem__(state, "store")
    rows = dict.__getitem__(state, "rows")
    tokenizer = dict.__getitem__(state, "tokenizer")
    tokens = dict.__getitem__(state, "tokens")
    tf_rows = dict.__getitem__(state, "tf")
    df = dict.__getitem__(state, "df")
    if (
        current_store is not authority.store
        or current_store is not store
        or rows is not authority.rows
        or tokenizer is not authority.tokenizer
        or type(tokenizer) is not authority.tokenizer_type
        or tokens is not authority.tokens
        or tf_rows is not authority.tf
        or df is not authority.df
    ):
        raise ValueError("loaded_lexical_snapshot_identity_drift")
    tokenizer_identity = object.__getattribute__(tokenizer, "identity")
    if tokenizer_identity is not authority.tokenizer_identity:
        raise ValueError("loaded_lexical_snapshot_identity_drift")
    avgdl = dict.__getitem__(state, "avgdl")
    artifact_sha256 = dict.__getitem__(state, "artifact_sha256")
    k1 = dict.__getitem__(state, "k1")
    b = dict.__getitem__(state, "b")
    if (
        type(rows) is not tuple
        or type(tokens) is not tuple
        or type(tf_rows) is not tuple
        or type(df) is not Counter
        or type(avgdl) is not float
        or type(k1) is not float
        or type(b) is not float
        or not math.isfinite(k1)
        or not math.isfinite(b)
        or k1 <= 0
        or not 0 <= b <= 1
    ):
        raise ValueError("loaded_lexical_snapshot_type_drift")
    _require_sha256(artifact_sha256, "loaded_lexical_snapshot_type_drift")
    if (
        avgdl != authority.avgdl
        or artifact_sha256 != authority.artifact_sha256
        or k1 != authority.k1
        or b != authority.b
    ):
        raise ValueError("loaded_lexical_issued_config_drift")
    if any(
        type(row) is not tuple
        or any(type(token) is not str or not token for token in row)
        for row in tokens
    ):
        raise ValueError("loaded_lexical_snapshot_type_drift")
    tf_snapshots = tuple(_counter_snapshot(counter) for counter in tf_rows)
    df_snapshot = _counter_snapshot(df)
    attestation = authority.attestation
    _validate_lexical_attestation_snapshot(
        attestation, authority.proof_payload
    )
    tokenizer_kind = object.__getattribute__(attestation, "tokenizer_kind")
    if tokenizer_kind == "real_kiwi":
        if (
            authority.query_tokenizer is None
            or authority.source_runtime is None
            or authority.query_runtime is None
            or authority.query_tokenizer_identity is None
        ):
            raise ValueError("loaded_lexical_runtime_attestation_missing")
        _validate_production_tokenizer_runtime(
            tokenizer,
            expected_runtime=authority.source_runtime,
            expected_identity=authority.tokenizer_identity,
        )
        _validate_production_tokenizer_runtime(
            authority.query_tokenizer,
            expected_runtime=authority.query_runtime,
            expected_identity=authority.query_tokenizer_identity,
        )
        if not object.__getattribute__(
            attestation, "tokenizer_runtime_sha256"
        ):
            raise ValueError("loaded_lexical_tokenizer_runtime_drift")
    elif any(
        value is not None
        for value in (
            authority.source_runtime,
            authority.query_tokenizer,
            authority.query_tokenizer_identity,
            authority.query_runtime,
        )
    ):
        raise ValueError("loaded_lexical_synthetic_runtime_drift")
    expected_tf_snapshots = tuple(_token_count_snapshot(row) for row in tokens)
    expected_df_counts = {}
    for snapshot in expected_tf_snapshots:
        for term, _count in snapshot:
            dict.__setitem__(
                expected_df_counts,
                term,
                dict.get(expected_df_counts, term, 0) + 1,
            )
    expected_df_snapshot = tuple(sorted(dict.items(expected_df_counts)))
    expected_avgdl = sum(map(len, tokens)) / max(1, len(tokens))
    if (
        tf_snapshots != expected_tf_snapshots
        or df_snapshot != expected_df_snapshot
        or avgdl != expected_avgdl
    ):
        raise ValueError("loaded_lexical_bm25_state_drift")
    store_bundle_sha256 = object.__getattribute__(store, "bundle_sha256")
    _require_sha256(
        store_bundle_sha256, "loaded_lexical_store_bundle_type_drift"
    )
    checks = {
        "bundle_sha256": store_bundle_sha256,
        "receipt_sha256": artifact_sha256,
        "tokens_content_sha256": _token_rows_hash(tokens),
        "tokenizer_identity_sha256": _digest(thaw(tokenizer_identity)),
        "config_sha256": _digest({"k1": k1, "b": b}),
    }
    if any(
        object.__getattribute__(attestation, name) != value
        for name, value in dict.items(checks)
    ):
        raise ValueError("loaded_lexical_runtime_drift")
    return attestation


def require_loaded_lexical_artifact(
    lane: KiwiBM25Lane,
    store: EvidenceStore,
    *,
    production: bool = False,
    _dependency_checker=None,
    _dependency_checker_code=None,
    _dependency_checker_defaults=None,
    _dependency_checker_globals=None,
) -> LoadedLexicalArtifactAttestation:
    """Return a loader proof after preflight and live-store validation."""

    module_globals = globals()
    if (
        _dependency_checker_globals is not module_globals
        or _dependency_checker_globals
        is not dict.get(module_globals, "_PRODUCTION_DISPATCH_GLOBALS")
        or _dependency_checker
        is not dict.get(
            module_globals,
            "_ISSUED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER",
        )
        or _dependency_checker
        is not dict.get(
            module_globals, "_validate_production_dispatch_dependencies"
        )
        or object.__getattribute__(_dependency_checker, "__code__")
        is not _dependency_checker_code
        or _dependency_checker_code
        is not dict.get(
            module_globals,
            "_PINNED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER_CODE",
        )
        or object.__getattribute__(_dependency_checker, "__globals__")
        is not module_globals
        or object.__getattribute__(_dependency_checker, "__defaults__")
        is not _dependency_checker_defaults
        or _dependency_checker_defaults
        is not dict.get(
            module_globals,
            "_PINNED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER_DEFAULTS",
        )
    ):
        raise ValueError("lexical_production_dispatch_dependency_drift")
    _dependency_checker()
    attestation = _ISSUED_PREFLIGHT_LOADED_LEXICAL_ARTIFACT(lane, store)
    authority = _lookup_loaded_lexical_authority(lane)
    if authority is None or authority.attestation is not attestation:
        raise ValueError("loaded_lexical_artifact_required")
    if (
        production
        and object.__getattribute__(attestation, "tokenizer_kind")
        != "real_kiwi"
    ):
        raise ValueError("loaded_lexical_production_tokenizer_required")

    # Store traversal is intentionally deferred until both runtime lanes can
    # complete their public zero-traversal preflights.
    try:
        validate_evidence_store_snapshot(store, authority.bundle_sha256)
    except ValueError as exc:
        raise ValueError("loaded_lexical_store_payload_drift") from exc
    state = _read_lane_state(lane)
    rows = dict.__getitem__(state, "rows")
    store_rows = store.candidates()
    if (
        len(rows) != len(store_rows)
        or any(issued is not actual for issued, actual in zip(rows, store_rows))
    ):
        raise ValueError("loaded_lexical_store_or_rows_mismatch")
    if object.__getattribute__(attestation, "rows_sha256") != _row_hash(
        store_rows
    ):
        raise ValueError("loaded_lexical_runtime_drift")
    return attestation


_ISSUED_PREFLIGHT_LOADED_LEXICAL_ARTIFACT = (
    preflight_loaded_lexical_artifact
)
_ISSUED_REQUIRE_LOADED_LEXICAL_ARTIFACT = require_loaded_lexical_artifact


def _validate_production_dispatch_dependencies(
    _module_globals=None,
    _function_pins=None,
    _identity_pins=None,
    _module_attribute_pins=None,
    _class_pins=None,
    _class_shape_pins=None,
    _external_global_pins=None,
    _registry_authority=None,
) -> None:
    """Verify the explicit callable/module allowlist without executing it."""

    module_globals = _module_globals
    if (
        type(module_globals) is not dict
        or globals() is not module_globals
        or any(
            authority is None
            for authority in (
                _function_pins,
                _identity_pins,
                _module_attribute_pins,
                _class_pins,
                _class_shape_pins,
                _external_global_pins,
                _registry_authority,
            )
        )
    ):
        raise ValueError("lexical_production_dispatch_dependency_drift")
    for name, issued, issued_code in _function_pins:
        current = dict.get(module_globals, name)
        if (
            current is not issued
            or type(current) is not FunctionType
            or object.__getattribute__(current, "__code__") is not issued_code
        ):
            raise ValueError("lexical_production_dispatch_dependency_drift")
    for name, issued in _identity_pins:
        if dict.get(module_globals, name) is not issued:
            raise ValueError("lexical_production_dispatch_dependency_drift")
    if (
        type(_registry_authority) is not tuple
        or len(_registry_authority) != 5
        or _registry_authority
        is not dict.get(
            module_globals, "_PRODUCTION_DISPATCH_REGISTRY_AUTHORITY"
        )
        or _registry_authority
        is not dict.get(
            module_globals, "_ISSUED_PRODUCTION_DISPATCH_REGISTRY_AUTHORITY"
        )
    ):
        raise ValueError("lexical_production_dispatch_dependency_drift")
    (
        registry,
        registry_type,
        authority_type,
        authority_size,
        reference_type,
    ) = _registry_authority
    if (
        registry_type is not dict
        or type(registry) is not registry_type
        or authority_type is not _LoadedLexicalAuthority
        or authority_size != _LOADED_LEXICAL_AUTHORITY_SIZE
        or reference_type is not ReferenceType
        or dict.get(module_globals, "_LOADED_LEXICAL_AUTHORITIES")
        is not registry
        or dict.get(module_globals, "_ISSUED_LOADED_LEXICAL_AUTHORITIES")
        is not registry
    ):
        raise ValueError("lexical_production_dispatch_dependency_drift")
    for identity, authority in dict.items(registry):
        if (
            type(identity) is not int
            or type(authority) is not authority_type
            or tuple.__len__(authority) != authority_size
        ):
            raise ValueError("loaded_lexical_authority_registry_drift")
        weak = tuple.__getitem__(authority, 0)
        if type(weak) is not reference_type:
            raise ValueError("loaded_lexical_authority_registry_drift")
    for owner, name, issued in _module_attribute_pins:
        state = object.__getattribute__(owner, "__dict__")
        if type(state) is not dict or dict.get(state, name) is not issued:
            raise ValueError("lexical_production_dispatch_dependency_drift")
    for owner, name, issued, issued_code in _class_pins:
        state = type.__getattribute__(owner, "__dict__")
        current = state.get(name)
        if current is not issued:
            raise ValueError("lexical_production_dispatch_dependency_drift")
        if issued_code is not None and (
            type(current) is not FunctionType
            or object.__getattribute__(current, "__code__") is not issued_code
        ):
            raise ValueError("lexical_production_dispatch_dependency_drift")
    for owner, issued_getattribute, descriptors in _class_shape_pins:
        state = type.__getattribute__(owner, "__dict__")
        if (
            type.__getattribute__(owner, "__getattribute__")
            is not issued_getattribute
            or any(
                state.get(name) is not issued
                for name, issued in descriptors
            )
        ):
            raise ValueError("lexical_production_dispatch_dependency_drift")
    for namespace, name, issued in _external_global_pins:
        if type(namespace) is not dict or dict.get(namespace, name) is not issued:
            raise ValueError("lexical_production_dispatch_dependency_drift")


_ISSUED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER = (
    _validate_production_dispatch_dependencies
)
_PINNED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER_CODE = (
    _validate_production_dispatch_dependencies.__code__
)
_PRODUCTION_DISPATCH_GLOBALS = globals()
_PRODUCTION_DISPATCH_FUNCTION_PINS = tuple(
    (name, function, object.__getattribute__(function, "__code__"))
    for name, function in (
        ("_kiwi_runtime_handle_is_pinned", _kiwi_runtime_handle_is_pinned),
        ("_digest", _digest),
        ("_row_hash", _row_hash),
        ("_token_rows_hash", _token_rows_hash),
        ("_require_pinned_attestation_descriptors", _require_pinned_attestation_descriptors),
        ("_require_sha256", _require_sha256),
        ("_validate_lexical_attestation_snapshot", _validate_lexical_attestation_snapshot),
        ("_require_pinned_tokenize_implementation", _require_pinned_tokenize_implementation),
        ("_tokenizer_state", _tokenizer_state),
        ("_validate_production_tokenizer_runtime", _validate_production_tokenizer_runtime),
        ("_lookup_loaded_lexical_authority", _lookup_loaded_lexical_authority),
        ("_require_pinned_search_implementation", _require_pinned_search_implementation),
        ("_read_lane_state", _read_lane_state),
        ("_counter_snapshot", _counter_snapshot),
        ("_token_count_snapshot", _token_count_snapshot),
        ("preflight_loaded_lexical_artifact", preflight_loaded_lexical_artifact),
        (
            "_ISSUED_PREFLIGHT_LOADED_LEXICAL_ARTIFACT",
            _ISSUED_PREFLIGHT_LOADED_LEXICAL_ARTIFACT,
        ),
        ("require_loaded_lexical_artifact", require_loaded_lexical_artifact),
        (
            "_ISSUED_REQUIRE_LOADED_LEXICAL_ARTIFACT",
            _ISSUED_REQUIRE_LOADED_LEXICAL_ARTIFACT,
        ),
        ("validate_search", validate_search),
        ("validate_evidence_store_snapshot", validate_evidence_store_snapshot),
        ("freeze", freeze),
        ("thaw", thaw),
        ("_validate_production_dispatch_dependencies", _validate_production_dispatch_dependencies),
        (
            "_ISSUED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER",
            _ISSUED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER,
        ),
    )
)
_PRODUCTION_DISPATCH_IDENTITY_PINS = (
    ("unicodedata", unicodedata),
    ("math", math),
    ("json", json),
    ("sha256", sha256),
    ("Counter", Counter),
    ("Candidate", Candidate),
    ("SearchResult", SearchResult),
    ("RetrievalProviderError", RetrievalProviderError),
    ("RetrievalPostCallContractError", RetrievalPostCallContractError),
    ("EvidenceStore", EvidenceStore),
    ("LoadedLexicalArtifactAttestation", LoadedLexicalArtifactAttestation),
    ("_LoadedLexicalAuthority", _LoadedLexicalAuthority),
    ("KiwiTokenizer", KiwiTokenizer),
    ("KiwiBM25Lane", KiwiBM25Lane),
    ("FunctionType", FunctionType),
    ("MemberDescriptorType", MemberDescriptorType),
    ("ReferenceType", ReferenceType),
    ("ref", ref),
    ("_LOADED_LEXICAL_AUTHORITIES", _LOADED_LEXICAL_AUTHORITIES),
    (
        "_ISSUED_LOADED_LEXICAL_AUTHORITIES",
        _ISSUED_LOADED_LEXICAL_AUTHORITIES,
    ),
    ("_PINNED_KIWI_CLASS", _PINNED_KIWI_CLASS),
    ("_PINNED_KIWI_RUNTIME_TOKENIZE", _PINNED_KIWI_RUNTIME_TOKENIZE),
    ("_PINNED_KIWI_RUNTIME_TOKENIZE_CODE", _PINNED_KIWI_RUNTIME_TOKENIZE_CODE),
    ("_PINNED_KIWI_TOKENIZE", _PINNED_KIWI_TOKENIZE),
    ("_PINNED_KIWI_TOKENIZE_CODE", _PINNED_KIWI_TOKENIZE_CODE),
    ("_LEXICAL_ATTESTATION_FIELDS", _LEXICAL_ATTESTATION_FIELDS),
    ("_LEXICAL_LANE_FIELDS", _LEXICAL_LANE_FIELDS),
    ("_PINNED_LEXICAL_ATTESTATION_DESCRIPTORS", _PINNED_LEXICAL_ATTESTATION_DESCRIPTORS),
)
_PRODUCTION_DISPATCH_MODULE_ATTRIBUTE_PINS = (
    (unicodedata, "normalize", unicodedata.normalize),
    (math, "log", math.log),
    (math, "isfinite", math.isfinite),
    (json, "dumps", json.dumps),
    (json, "loads", json.loads),
)
_PRODUCTION_DISPATCH_CLASS_PINS = tuple(
    (
        owner,
        name,
        member,
        object.__getattribute__(member, "__code__")
        if type(member) is FunctionType
        else None,
    )
    for owner, name, member in (
        (Counter, "__init__", Counter.__dict__["__init__"]),
        (Candidate, "__init__", Candidate.__dict__["__init__"]),
        (Candidate, "__post_init__", Candidate.__dict__["__post_init__"]),
        (SearchResult, "__init__", SearchResult.__dict__["__init__"]),
        (SearchResult, "__post_init__", SearchResult.__dict__["__post_init__"]),
    )
)
_PRODUCTION_DISPATCH_CLASS_SHAPE_PINS = tuple(
    (
        owner,
        type.__getattribute__(owner, "__getattribute__"),
        tuple(
            (name, type.__getattribute__(owner, "__dict__")[name])
            for name in fields
        ),
    )
    for owner, fields in (
        (
            Candidate,
            (
                "evidence_id",
                "doc_id",
                "score",
                "lane",
                "rank",
                "granularity",
            ),
        ),
        (SearchResult, ("candidates", "trace")),
        (_LoadedLexicalAuthority, _LoadedLexicalAuthority._fields),
    )
)
_PRODUCTION_DISPATCH_CONTRACT_GLOBALS = object.__getattribute__(
    validate_search, "__globals__"
)
_PRODUCTION_DISPATCH_EXTERNAL_GLOBAL_PINS = (
    (_PRODUCTION_DISPATCH_CONTRACT_GLOBALS, "math", math),
    (_PRODUCTION_DISPATCH_CONTRACT_GLOBALS, "json", json),
    (_PRODUCTION_DISPATCH_CONTRACT_GLOBALS, "freeze", freeze),
    (_PRODUCTION_DISPATCH_CONTRACT_GLOBALS, "thaw", thaw),
    (_PRODUCTION_DISPATCH_CONTRACT_GLOBALS, "Candidate", Candidate),
    (
        _PRODUCTION_DISPATCH_CONTRACT_GLOBALS,
        "SearchResult",
        SearchResult,
    ),
    (
        _PRODUCTION_DISPATCH_CONTRACT_GLOBALS,
        "Mapping",
        dict.get(_PRODUCTION_DISPATCH_CONTRACT_GLOBALS, "Mapping"),
    ),
    (
        _PRODUCTION_DISPATCH_CONTRACT_GLOBALS,
        "MappingProxyType",
        dict.get(_PRODUCTION_DISPATCH_CONTRACT_GLOBALS, "MappingProxyType"),
    ),
)
_PRODUCTION_DISPATCH_REGISTRY_AUTHORITY = (
    _LOADED_LEXICAL_AUTHORITIES,
    dict,
    _LoadedLexicalAuthority,
    _LOADED_LEXICAL_AUTHORITY_SIZE,
    ReferenceType,
)
_ISSUED_PRODUCTION_DISPATCH_REGISTRY_AUTHORITY = (
    _PRODUCTION_DISPATCH_REGISTRY_AUTHORITY
)

# Function defaults hold the issued authority snapshots independently of the
# mutable module names. Production call sites always invoke this checker with
# no arguments, so swapping a manifest global cannot bless a second program.
_validate_production_dispatch_dependencies.__defaults__ = (
    _PRODUCTION_DISPATCH_GLOBALS,
    _PRODUCTION_DISPATCH_FUNCTION_PINS,
    _PRODUCTION_DISPATCH_IDENTITY_PINS,
    _PRODUCTION_DISPATCH_MODULE_ATTRIBUTE_PINS,
    _PRODUCTION_DISPATCH_CLASS_PINS,
    _PRODUCTION_DISPATCH_CLASS_SHAPE_PINS,
    _PRODUCTION_DISPATCH_EXTERNAL_GLOBAL_PINS,
    _PRODUCTION_DISPATCH_REGISTRY_AUTHORITY,
)
_PINNED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER_DEFAULTS = (
    _validate_production_dispatch_dependencies.__defaults__
)

for _public_lexical_entry in (
    preflight_loaded_lexical_artifact,
    require_loaded_lexical_artifact,
):
    object.__getattribute__(_public_lexical_entry, "__kwdefaults__").update(
        {
            "_dependency_checker": (
                _ISSUED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER
            ),
            "_dependency_checker_code": (
                _PINNED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER_CODE
            ),
            "_dependency_checker_defaults": (
                _PINNED_PRODUCTION_DISPATCH_DEPENDENCY_CHECKER_DEFAULTS
            ),
            "_dependency_checker_globals": _PRODUCTION_DISPATCH_GLOBALS,
        }
    )
del _public_lexical_entry
