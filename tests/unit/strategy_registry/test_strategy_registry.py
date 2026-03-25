"""Tests for the strategy registry (src/strategies/registry.py)."""
from __future__ import annotations

import pytest


def _fresh_registry():
    """Force re-discovery by clearing the singleton."""
    import src.strategies.registry as reg
    reg._registry = None
    return reg


class TestDiscovery:
    def test_discovers_atr_mean_reversion(self):
        reg = _fresh_registry()
        all_strats = reg.get_all()
        assert "atr_mean_reversion" in all_strats
        info = all_strats["atr_mean_reversion"]
        assert info.factory == "create_atr_mean_reversion_engine"
        assert info.module == "src.strategies.atr_mean_reversion"

    def test_discovers_pyramid_wrapper(self):
        reg = _fresh_registry()
        all_strats = reg.get_all()
        assert "pyramid_wrapper" in all_strats
        info = all_strats["pyramid_wrapper"]
        assert info.factory == "create_pyramid_engine"

    def test_skips_files_without_param_schema(self):
        reg = _fresh_registry()
        all_strats = reg.get_all()
        assert "example_entry" not in all_strats
        assert "example_stop" not in all_strats
        assert "example_add" not in all_strats

    def test_skips_private_files(self):
        reg = _fresh_registry()
        all_strats = reg.get_all()
        assert "__init__" not in all_strats


class TestGetSchema:
    def test_returns_correct_structure(self):
        reg = _fresh_registry()
        schema = reg.get_schema("atr_mean_reversion")
        assert schema["strategy"] == "atr_mean_reversion"
        assert "parameters" in schema
        assert "meta" in schema

    def test_all_params_present(self):
        reg = _fresh_registry()
        schema = reg.get_schema("atr_mean_reversion")
        expected = {"bb_len", "bb_upper_mult", "bb_lower_mult", "rsi_len",
                    "atr_len", "atr_sl_multi", "atr_tp_multi", "trend_ma_len",
                    "rsi_oversold", "rsi_overbought"}
        assert set(schema["parameters"].keys()) == expected

    def test_param_has_required_fields(self):
        reg = _fresh_registry()
        schema = reg.get_schema("atr_mean_reversion")
        bb = schema["parameters"]["bb_len"]
        assert "current" in bb
        assert "type" in bb
        assert "description" in bb

    def test_meta_populated(self):
        reg = _fresh_registry()
        schema = reg.get_schema("atr_mean_reversion")
        assert schema["meta"].get("recommended_timeframe") == "intraday"

    def test_unknown_strategy_raises_keyerror(self):
        reg = _fresh_registry()
        with pytest.raises(KeyError, match="nonexistent"):
            reg.get_schema("nonexistent")


class TestGetActiveParams:
    def test_returns_defaults_without_toml(self):
        reg = _fresh_registry()
        params = reg.get_active_params("atr_mean_reversion")
        assert params["bb_len"] == 40
        assert params["atr_sl_multi"] == 3.5

    def test_merges_toml_override(self, tmp_path):
        import tomli_w
        reg = _fresh_registry()
        toml_dir = tmp_path / "configs"
        toml_dir.mkdir()
        (toml_dir / "atr_mean_reversion.toml").write_bytes(
            tomli_w.dumps({"params": {"bb_len": 20}}).encode()
        )
        import src.strategies.param_loader as pl
        orig_dir = pl._CONFIGS_DIR
        pl._CONFIGS_DIR = toml_dir
        try:
            params = reg.get_active_params("atr_mean_reversion")
            assert params["bb_len"] == 20
            assert params["atr_sl_multi"] == 3.5
        finally:
            pl._CONFIGS_DIR = orig_dir


class TestGetParamGrid:
    def test_grid_from_schema(self):
        reg = _fresh_registry()
        grid = reg.get_param_grid("atr_mean_reversion")
        assert grid["bb_len"]["default"] == [15, 20, 25]
        assert grid["rsi_oversold"]["default"] == [25, 30]

    def test_fallback_to_single_default(self):
        reg = _fresh_registry()
        grid = reg.get_param_grid("atr_mean_reversion")
        assert grid["rsi_len"]["default"] == [5]

    def test_grid_has_label_and_type(self):
        reg = _fresh_registry()
        grid = reg.get_param_grid("atr_mean_reversion")
        assert "label" in grid["bb_len"]
        assert "type" in grid["bb_len"]


class TestRegister:
    def test_explicit_registration(self):
        reg = _fresh_registry()
        reg.register(
            slug="test_strategy",
            module="tests.test_strategy_registry",
            factory="fake_factory",
            param_schema={"param1": {"type": "float", "default": 1.0, "description": "test"}},
        )
        schema = reg.get_schema("test_strategy")
        assert schema["strategy"] == "test_strategy"
        assert "param1" in schema["parameters"]

    def test_registration_overwrites(self):
        reg = _fresh_registry()
        reg.register("test_ow", "mod1", "fn1", {"a": {"type": "int", "default": 1, "description": ""}})
        reg.register("test_ow", "mod2", "fn2", {"b": {"type": "float", "default": 2.0, "description": ""}})
        schema = reg.get_schema("test_ow")
        assert "b" in schema["parameters"]
        assert "a" not in schema["parameters"]


class TestValidateSchemas:
    def test_consistent_schemas_pass(self):
        reg = _fresh_registry()
        errors = reg.validate_schemas()
        assert errors == [], f"Unexpected validation errors: {errors}"


class TestSchemaFactoryConsistency:
    """Verify that every PARAM_SCHEMA matches its factory's kwargs."""

    def test_all_strategies_consistent(self):
        import inspect
        from src.strategies.registry import get_all
        skip_params = {"max_loss", "lots", "contract_type"}
        for slug, info in get_all().items():
            import importlib
            mod = importlib.import_module(info.module)
            fn = getattr(mod, info.factory)
            sig = inspect.signature(fn)
            factory_kw = {
                k for k, v in sig.parameters.items()
                if k not in skip_params and v.default is not inspect.Parameter.empty
            }
            schema_keys = set(info.param_schema.keys())
            # If factory takes a config dataclass, skip direct comparison
            if not factory_kw:
                continue
            assert schema_keys == factory_kw, (
                f"{slug}: PARAM_SCHEMA keys {schema_keys} != factory kwargs {factory_kw}"
            )
