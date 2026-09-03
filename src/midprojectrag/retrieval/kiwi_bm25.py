"""Independent Korean morphological BM25 lane; no dense candidate dependency."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from importlib.metadata import version
import json
import math
from pathlib import Path
import unicodedata

from midprojectrag.evidence import EvidenceStore
from midprojectrag.evidence.artifacts import file_sha, private_path, write_new_json
from .contracts import Candidate, SearchResult, freeze, thaw, validate_search


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class KiwiTokenizer:
    def __init__(self, *, user_dictionary: tuple[tuple[str, str, float], ...] = ()):
        try:
            import kiwipiepy_model
            from kiwipiepy import Kiwi
        except ImportError as error:
            raise RuntimeError("kiwi_dependency_unavailable") from error
        if version("kiwipiepy") != "0.23.2" or version("kiwipiepy_model") != "0.23.0":
            raise RuntimeError("kiwi_version_not_pinned")
        model_path = Path(kiwipiepy_model.get_model_path())
        files = {p.name: file_sha(p) for p in sorted(model_path.iterdir())
                 if p.is_file() and p.suffix in {".mdl", ".morph", ".dict", ".txt"}}
        if not {"cong.mdl", "default.dict", "sj.morph"} <= files.keys():
            raise RuntimeError("kiwi_model_files_missing")
        dictionary = tuple(tuple(row) for row in user_dictionary)
        if any(len(row) != 3 or type(row[0]) is not str or not row[0] or type(row[1]) is not str
               or type(row[2]) not in (float, int) or not math.isfinite(row[2]) for row in dictionary):
            raise ValueError("invalid_kiwi_user_dictionary")
        self._kiwi = Kiwi(num_workers=1, model_path=str(model_path), model_type="cong",
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

    def search(self, query, limit, *, allowed_doc_ids=None):
        validate_search(query, limit, allowed_doc_ids)
        indices = [i for i, e in enumerate(self.rows) if allowed_doc_ids is None or e.doc_id in allowed_doc_ids]
        trace = {"lane": "lexical", "engine": "kiwi_bm25", "granularity": "child",
                 "bundle_sha256": self.store.bundle_sha256, "artifact_sha256": self.artifact_sha256,
                 "tokenizer_identity": thaw(self.tokenizer.identity), "requested_k": limit,
                 "scoped_rows": len(indices), "k1": self.k1, "b": self.b}
        if not indices:
            return SearchResult((), trace | {"query_tokens": [], "tokenizer_calls": 0, "empty_scope": True})
        tokens = self.tokenizer.tokenize(query)
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
        return SearchResult(candidates, trace | {"query_tokens": list(tokens), "tokenizer_calls": 1})

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
        return cls(store, tokenizer, [r["tokens"] for r in payload], k1=receipt["k1"], b=receipt["b"],
                   artifact_sha256=file_sha(target / "receipt.json"))
