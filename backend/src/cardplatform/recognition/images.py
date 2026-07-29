"""Local cache of catalog card images, used to build the reference embedding index.

Filenames are derived from `card_id`, never from the URL: 661 of the 20,444 catalog
images are served from images.scrydex.com with no file extension (they end in '/small'),
so URL-based naming would corrupt 3% of the cache.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import httpx
from PIL import Image

from cardplatform.config import Settings, settings as default_settings

logger = logging.getLogger(__name__)


class ReferenceImageCache:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings
        self.directory = self.settings.reference_image_dir
        self.directory.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(
            timeout=self.settings.http_timeout_seconds, follow_redirects=True
        )

    def path_for(self, card_id: str) -> Path:
        return self.directory / f"{card_id}.png"

    def is_cached(self, card_id: str) -> bool:
        return self.path_for(card_id).exists()

    def fetch(self, card_id: str, url: str) -> Path | None:
        """Download and cache one image. Returns None on any failure — a missing
        reference image must degrade the index, not abort the whole build."""
        target = self.path_for(card_id)
        if target.exists():
            return target

        try:
            response = self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("reference image fetch failed for %s: %s", card_id, exc)
            return None

        try:
            # Decode before writing: a truncated or non-image body must not leave a
            # file behind that later looks cached.
            image = Image.open(io.BytesIO(response.content)).convert("RGB")
        except Exception as exc:  # noqa: BLE001 - PIL raises a wide variety here
            logger.warning("reference image unreadable for %s: %s", card_id, exc)
            return None

        image.save(target, "PNG")
        return target

    def load(self, card_id: str) -> Image.Image | None:
        path = self.path_for(card_id)
        if not path.exists():
            return None
        return Image.open(path).convert("RGB")
