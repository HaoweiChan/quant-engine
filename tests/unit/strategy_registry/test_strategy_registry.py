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
        slug = "short_term/mean_reversion/atr_mean_reversion"
        assert slug in all_strats
        info = all_strats[slug]
        assert info.factory == "create_atr_mean_reversion_engine"
        assert info.module == "src.strategies.short_term.mean_reversion.atr_mean_reversion"

    def test_discovers_pyramid_wrapper(self):
        reg = _fresh_registry()
        all_strats = reg.get_all()
        slug = "swing/trend_following/pyramid_wrapper"
        assert slug in all_strats
        info = all_strats[slug]
        assert info.factory == "create_pyramid_wrapper_engine"

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
        assert schema["strategy"] == "short_term/mean_reversion/atr_mean_reversion"
        assert "parameters" in schema
        assert "meta" in schema

    def test_all_params_present(self):
        reg = _fresh_registry()
        schema = reg.get_schema("atr_mean_reversion")
        # Core params that must always be present
        required = {"kc_len", "kc_mult", "rsi_len", "atr_sl_multi", "atr_tp_multi",
                    "trend_ma_len", "rsi_oversold", "rsi_overbought"}
        assert required.issubset(set(schema["parameters"].keys()))

    def test_param_has_required_fields(self):
        reg = _fresh_registry()
        schema = reg.get_schema("atr_mean_reversion")
        kc = schema["parameters"]["kc_len"]
        assert "current" in kc
        assert "type" in kc
        assert "description" in kc

    def test_meta_populated(self):
        reg = _fresh_registry()
        schema = reg.get_schema("atr_mean_reversion")
        assert "description" in schema["meta"]

    def test_unknown_strategy_raises_keyerror(self):
        reg = _fresh_registry()
        with pytest.raises(KeyError, match="nonexistent"):
            reg.get_schema("nonexistent")


class TestGetActiveParams:
    def test_returns_defaults_without_toml(self, monkeypatch):
        reg = _fresh_registry()
        from src.strategies import param_registry as pr
        monkeypatch.setattr(pr.ParamRegistry, "get_active", lambda self, name: None)
        params = reg.get_active_params("atr_mean_reversion")
        assert params["kc_len"] == 90
        assert params["atr_sl_multi"] == 1.5

    def test_merges_toml_override(self, tmp_path, monkeypatch):
        import tomli_w
        reg = _fresh_registry()
        toml_dir = tmp_path / "configs"
        toml_file = toml_dir / "short_term" / "mean_reversion"
        toml_file.mkdir(parents=True)
        (toml_file / "atr_mean_reversion.toml").write_bytes(
            tomli_w.dumps({"params": {"kc_len": 60}}).encode()
        )
        import src.strategies.param_loader as pl
        monkeypatch.setattr(pl, "_CONFIGS_DIR", toml_dir)
        from src.strategies import param_registry as pr
        monkeypatch.setattr(pr.ParamRegistry, "get_active", lambda self, name: None)
        params = reg.get_active_params("atr_mean_reversion")
        assert params["kc_len"] == 60
        assert params["atr_sl_multi"] == 1.5


class TestGetParamGrid:
    def test_grid_from_schema(self):
        reg = _fresh_registry()
        grid = reg.get_param_grid("atr_mean_reversion")
        assert grid["kc_len"]["default"] == [90]
        assert grid["kc_len"]["min"] == 10
        assert grid["kc_len"]["max"] == 300

    def test_fallback_to_single_default(self):
        reg = _fresh_registry()
        grid = reg.get_param_grid("atr_mean_reversion")
        assert grid["rsi_len"]["default"] == [3]
        assert grid["rsi_len"]["min"] == 2
        assert grid["rsi_len"]["max"] == 14

    def test_grid_has_label_and_type(self):
        reg = _fresh_registry()
        grid = reg.get_param_grid("atr_mean_reversion")
        assert "label" in grid["kc_len"]
        assert "type" in grid["kc_len"]


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
        import dataclasses
        import inspect
        from src.strategies.registry import get_all
        skip_params = {"max_loss", "lots", "contract_type", "latest_entry_time", "pyramid_risk_level"}
        for slug, info in get_all().items():
            import importlib
            mod = importlib.import_module(info.module)
            fn = getattr(mod, info.factory)
            sig = inspect.signature(fn)
            positional = [
                p for p in sig.parameters.values()
                if p.name not in skip_params and p.default is inspect.Parameter.empty
            ]
            # Detect config-dataclass factories via __globals__ resolution
            is_config_factory = False
            if len(positional) == 1:
                ann = positional[0].annotation
                if isinstance(ann, str):
                    ann = getattr(fn, "__globals__", {}).get(ann, ann)
                if not isinstance(ann, str) and dataclasses.is_dataclass(ann):
                    is_config_factory = True
            if is_config_factory:
                continue
            factory_kw = {
                k for k, v in sig.parameters.items()
                if k not in skip_params and v.default is not inspect.Parameter.empty
            }
            schema_keys = set(info.param_schema.keys())
            if not factory_kw:
                continue
            assert schema_keys == factory_kw, (
                f"{slug}: PARAM_SCHEMA keys {schema_keys} != factory kwargs {factory_kw}"
            )
