from types import SimpleNamespace

import pytest

from streamlit_demo import app


def test_missing_merged_fails_before_embedding(monkeypatch):
    app.load_runtime.clear()
    monkeypatch.setattr(app, "load_chunks", lambda: [SimpleNamespace(doc_id="fixture")])
    monkeypatch.setattr(app, "load_merged", lambda: None)

    def forbidden():
        raise AssertionError("Embedding must not load without corpus prerequisites")

    monkeypatch.setattr(app, "SentenceTransformerEmbedding", forbidden)
    with pytest.raises(FileNotFoundError, match="merged_docs.pkl"):
        app.load_runtime()
    app.load_runtime.clear()


def test_custom_local_model_tag_preserved():
    assert app._split_model_choice("qwen3-8b:qwen3:8b") == ("qwen3-8b", "qwen3:8b")
