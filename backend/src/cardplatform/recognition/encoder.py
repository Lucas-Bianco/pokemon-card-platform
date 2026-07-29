"""Wraps the CLIP image encoder.

Measured on an RTX 5070 Ti: 2.2 ms/card, 512-d vectors, so the full 20,444-card catalog
embeds in about 40 seconds. Vectors are L2-normalized on the way out, which lets FAISS
inner-product search act as cosine similarity.
"""

from __future__ import annotations

import logging

import numpy as np
import torch
from PIL import Image

from cardplatform.config import Settings, settings as default_settings

logger = logging.getLogger(__name__)


class CardEncoder:
    def __init__(self, settings: Settings | None = None) -> None:
        import open_clip

        self.settings = settings or default_settings
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        if self.device == "cpu":
            logger.warning(
                "CUDA unavailable — encoding will be roughly 20x slower. "
                "Check that torch was installed from the cu128 index."
            )

        model, _, preprocess = open_clip.create_model_and_transforms(
            self.settings.encoder_model, pretrained=self.settings.encoder_pretrained
        )
        self._model = model.to(self.device).eval()
        self._preprocess = preprocess
        self.dimension = int(self._model.visual.output_dim)

    def embed(self, image: Image.Image) -> np.ndarray:
        return self.embed_many([image])[0]

    def embed_many(self, images: list[Image.Image], batch_size: int = 128) -> np.ndarray:
        if not images:
            return np.empty((0, self.dimension), dtype=np.float32)

        chunks: list[np.ndarray] = []
        with torch.no_grad():
            for start in range(0, len(images), batch_size):
                batch = images[start : start + batch_size]
                tensor = torch.stack([self._preprocess(im) for im in batch]).to(self.device)
                vectors = self._model.encode_image(tensor)
                vectors = vectors / vectors.norm(dim=-1, keepdim=True)
                chunks.append(vectors.cpu().numpy().astype(np.float32))
        return np.vstack(chunks)
