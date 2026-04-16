"""Tests for code_hash module — strategy file hashing utilities."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.strategies.code_hash import compute_strategy_hash, strategy_file_path


class TestStrategyFilePath:
    def test_returns_path_for_known_slug(self) -> None:
        path = strategy_file_path("pyramid")
        assert path.exists()
        assert path.suffix == ".py"

    def test_resolves_alias(self) -> None:
        path = strategy_file_path("pyramid")
        assert "swing/trend_following/pyramid_wrapper" in str(path)

    def test_raises_on_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            strategy_file_path("nonexistent_strategy_slug_xyz")


class TestComputeStrategyHash:
    def test_returns_hex_digest_and_source(self) -> None:
        h, src = compute_strategy_hash("pyramid")
        assert isinstance(h, str)
        assert len(h) == 64
        assert src is not None
        assert len(src) > 0

    def test_deterministic_hash(self) -> None:
        h1, _ = compute_strategy_hash("pyramid")
        h2, _ = compute_strategy_hash("pyramid")
        assert h1 == h2

    def test_hash_changes_on_edit(self, tmp_path: Path) -> None:
        strategies_dir = Path(__file__).resolve().parents[2] / "src" / "strategies"
        test_file = strategies_dir / "swing" / "trend_following" / "pyramid_wrapper.py"
        original_content = test_file.read_text()
        try:
            test_file.write_text(original_content + "\n# test comment\n")
            h1, _ = compute_strategy_hash("pyramid")
            test_file.write_text(original_content + "\n# another test\n")
            h2, _ = compute_strategy_hash("pyramid")
            assert h1 != h2
        finally:
            test_file.write_text(original_content)

    def test_hash_matches_manual_sha256(self) -> None:
        h, src = compute_strategy_hash("pyramid")
        expected = hashlib.sha256(src.encode("utf-8")).hexdigest()
        assert h == expected

    def test_raises_on_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            compute_strategy_hash("nonexistent_strategy_slug_xyz")
