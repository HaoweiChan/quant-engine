"""Tests for src/dashboard/editor.py — path validation, file I/O, and validation."""
from __future__ import annotations

import pytest

from src.dashboard.editor import (
    _validate_path,
    check_syntax,
    list_editable_files,
    read_file,
    run_ruff,
    validate_engine,
    write_file,
)


class TestPathValidation:
    def test_valid_strategies_path(self) -> None:
        p = _validate_path("src/strategies/example_entry.py")
        assert p.name == "example_entry.py"

    def test_valid_configs_path(self) -> None:
        p = _validate_path("src/strategies/configs/default.toml")
        assert p.name == "default.toml"

    def test_core_blocked(self) -> None:
        with pytest.raises(ValueError, match="not in allowed"):
            _validate_path("src/core/types.py")

    def test_bar_simulator_blocked(self) -> None:
        with pytest.raises(ValueError, match="not in allowed"):
            _validate_path("src/bar_simulator/models.py")

    def test_dashboard_blocked(self) -> None:
        with pytest.raises(ValueError, match="not in allowed"):
            _validate_path("src/dashboard/app.py")

    def test_traversal_blocked(self) -> None:
        with pytest.raises(ValueError, match="not in allowed"):
            _validate_path("src/strategies/../../core/types.py")


class TestListFiles:
    def test_returns_strategies_files(self) -> None:
        files = list_editable_files()
        dirs = {f["dir"] for f in files}
        assert any("strategies" in d for d in dirs)

    def test_excludes_dunder_files(self) -> None:
        files = list_editable_files()
        names = [f["name"] for f in files]
        assert "__init__.py" not in names

    def test_includes_toml_files(self) -> None:
        files = list_editable_files()
        extensions = {f["name"].rsplit(".", 1)[-1] for f in files}
        assert "toml" in extensions

    def test_no_core_files(self) -> None:
        files = list_editable_files()
        for f in files:
            assert "src/core" not in f["path"]


class TestReadWrite:
    def test_read_existing_file(self) -> None:
        content = read_file("src/strategies/example_entry.py")
        assert "MyEntryPolicy" in content

    def test_write_and_read_roundtrip(self, tmp_path, monkeypatch) -> None:
        import src.dashboard.editor as editor
        test_dir = tmp_path / "src" / "strategies"
        test_dir.mkdir(parents=True)
        monkeypatch.setattr(editor, "ALLOWED_DIRS", [test_dir])
        monkeypatch.setattr(editor, "_PROJECT_ROOT", tmp_path)
        test_file = test_dir / "test_mod.py"
        test_file.write_text("# original")
        write_file("src/strategies/test_mod.py", "# updated")
        assert read_file("src/strategies/test_mod.py") == "# updated"


class TestSyntaxCheck:
    def test_valid_code(self) -> None:
        result = check_syntax("x = 1\n")
        assert result == {"ok": True}

    def test_syntax_error(self) -> None:
        result = check_syntax("def foo(\n")
        assert result["ok"] is False
        assert "line" in result
        assert "msg" in result


class TestRuff:
    def test_clean_code(self) -> None:
        issues = run_ruff("x = 1\n", "test.py")
        assert isinstance(issues, list)

    def test_unused_import(self) -> None:
        issues = run_ruff("import os\nx = 1\n", "test.py")
        rules = [i["rule"] for i in issues]
        assert any("F401" in str(r) for r in rules)


class TestEngineValidation:
    def test_current_strategies_validate(self) -> None:
        err = validate_engine()
        assert err is None, f"Engine validation failed: {err}"
