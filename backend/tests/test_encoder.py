import numpy as np
import pytest
from PIL import Image

from cardplatform.config import Settings
from cardplatform.recognition.encoder import CardEncoder


@pytest.fixture(scope="module")
def encoder():
    return CardEncoder(Settings())


def _solid(color) -> Image.Image:
    return Image.new("RGB", (600, 825), color)


def test_embed_returns_unit_vector(encoder):
    vector = encoder.embed(_solid((200, 40, 40)))

    assert vector.shape == (encoder.dimension,)
    assert vector.dtype == np.float32
    assert np.isclose(np.linalg.norm(vector), 1.0, atol=1e-4)


def test_dimension_is_512_for_vit_b_32(encoder):
    assert encoder.dimension == 512


def test_embed_many_matches_embed_one(encoder):
    images = [_solid((200, 40, 40)), _solid((40, 200, 40))]

    batch = encoder.embed_many(images)

    assert batch.shape == (2, encoder.dimension)
    assert np.allclose(batch[0], encoder.embed(images[0]), atol=1e-4)


def test_identical_images_are_more_similar_than_different_ones(encoder):
    red_a = encoder.embed(_solid((200, 40, 40)))
    red_b = encoder.embed(_solid((200, 40, 40)))
    green = encoder.embed(_solid((40, 200, 40)))

    assert float(red_a @ red_b) > float(red_a @ green)


def test_embed_many_of_empty_list_returns_empty_array(encoder):
    result = encoder.embed_many([])

    assert result.shape == (0, encoder.dimension)
