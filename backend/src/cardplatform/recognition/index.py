"""FAISS index over reference card embeddings.

At 20,444 vectors an exact inner-product index searches in ~0.01 ms, so there is no
reason to accept the accuracy loss of an approximate index. Vectors arrive normalized
from CardEncoder, which makes inner product equal to cosine similarity.
"""

from __future__ import annotations

import json

import faiss
import numpy as np

from cardplatform.config import Settings, settings as default_settings
from cardplatform.recognition.types import Candidate


class CardIndex:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings
        self._index: faiss.Index | None = None
        self._card_ids: list[str] = []

    @property
    def size(self) -> int:
        return 0 if self._index is None else self._index.ntotal

    def build(self, card_ids: list[str], vectors: np.ndarray) -> "CardIndex":
        if len(card_ids) != len(vectors):
            raise ValueError(
                f"card_ids and vectors length mismatch: {len(card_ids)} vs {len(vectors)}"
            )
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(np.ascontiguousarray(vectors, dtype=np.float32))
        self._index = index
        self._card_ids = list(card_ids)
        return self

    def save(self) -> None:
        if self._index is None:
            raise RuntimeError("index not loaded; build it before saving")
        self.settings.ensure_dirs()
        faiss.write_index(self._index, str(self.settings.index_path))
        self.settings.index_ids_path.write_text(
            json.dumps(self._card_ids), encoding="utf-8"
        )

    def load(self) -> "CardIndex":
        if not self.settings.index_path.exists() or not self.settings.index_ids_path.exists():
            raise FileNotFoundError(
                f"no index at {self.settings.index_path}; run 'cardplatform build-index' first"
            )
        self._index = faiss.read_index(str(self.settings.index_path))
        self._card_ids = json.loads(
            self.settings.index_ids_path.read_text(encoding="utf-8")
        )
        return self

    def search(self, vector: np.ndarray, top_k: int) -> list[Candidate]:
        if self._index is None:
            raise RuntimeError("index not loaded; call build() or load() first")
        query = np.ascontiguousarray(vector.reshape(1, -1), dtype=np.float32)
        scores, positions = self._index.search(query, min(top_k, self._index.ntotal))
        return [
            Candidate(card_id=self._card_ids[position], visual_score=float(score))
            for score, position in zip(scores[0], positions[0])
            if position != -1
        ]
