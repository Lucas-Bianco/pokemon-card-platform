import numpy as np
import pytest

from cardplatform.config import Settings
from cardplatform.recognition.index import CardIndex


def _unit(values) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


@pytest.fixture
def vectors():
    return np.vstack([_unit([1, 0, 0]), _unit([0, 1, 0]), _unit([0, 0, 1])])


def test_build_and_search_returns_nearest_first(tmp_path, vectors):
    index = CardIndex(Settings(data_dir=tmp_path))
    index.build(["a", "b", "c"], vectors)

    results = index.search(_unit([0.9, 0.1, 0]), top_k=2)

    assert [c.card_id for c in results] == ["a", "b"]
    assert results[0].visual_score > results[1].visual_score


def test_search_scores_are_cosine_similarity(tmp_path, vectors):
    index = CardIndex(Settings(data_dir=tmp_path))
    index.build(["a", "b", "c"], vectors)

    results = index.search(_unit([1, 0, 0]), top_k=1)

    assert results[0].visual_score == pytest.approx(1.0, abs=1e-5)


def test_save_and_load_roundtrip(tmp_path, vectors):
    settings = Settings(data_dir=tmp_path)
    CardIndex(settings).build(["a", "b", "c"], vectors).save()

    reloaded = CardIndex(settings)
    reloaded.load()

    assert reloaded.size == 3
    assert [c.card_id for c in reloaded.search(_unit([0, 1, 0]), top_k=1)] == ["b"]


def test_load_without_saved_index_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="no index"):
        CardIndex(Settings(data_dir=tmp_path)).load()


def test_search_before_build_raises(tmp_path):
    with pytest.raises(RuntimeError, match="not loaded"):
        CardIndex(Settings(data_dir=tmp_path)).search(_unit([1, 0, 0]), top_k=1)


def test_build_rejects_mismatched_lengths(tmp_path, vectors):
    with pytest.raises(ValueError, match="length"):
        CardIndex(Settings(data_dir=tmp_path)).build(["a", "b"], vectors)


def test_top_k_larger_than_index_is_clamped(tmp_path, vectors):
    index = CardIndex(Settings(data_dir=tmp_path))
    index.build(["a", "b", "c"], vectors)

    assert len(index.search(_unit([1, 0, 0]), top_k=50)) == 3
