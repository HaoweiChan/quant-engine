"""Tests for SecretManager, config loading, and error types."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.secrets.config import load_secret_names
from src.secrets.errors import SecretAccessError, SecretNotFoundError
from src.secrets.manager import SecretManager


class TestLoadSecretNames:
    def test_parses_valid_toml(self, tmp_path: Path) -> None:
        f = tmp_path / "secrets.toml"
        f.write_text('[sinopac]\napi_key = "SHIOAJI_API_KEY"\nsecret_key = "SHIOAJI_SECRET_KEY"\n')
        result = load_secret_names(f)
        assert result == {
            "sinopac": {
                "api_key": "SHIOAJI_API_KEY",
                "secret_key": "SHIOAJI_SECRET_KEY",
            }
        }

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="Secrets config not found"):
            load_secret_names(tmp_path / "nope.toml")

    def test_empty_toml_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "secrets.toml"
        f.write_text("")
        result = load_secret_names(f)
        assert result == {}

    def test_multiple_groups(self, tmp_path: Path) -> None:
        f = tmp_path / "secrets.toml"
        f.write_text(
            '[sinopac]\napi_key = "A"\n\n[other]\ntoken = "B"\n'
        )
        result = load_secret_names(f)
        assert "sinopac" in result
        assert "other" in result
        assert result["other"]["token"] == "B"


class TestSecretManagerGet:
    def _make_manager(self) -> tuple[SecretManager, MagicMock]:
        with patch(
            "src.secrets.manager.SecretManagerServiceClient"
        ) as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client
            sm = SecretManager(project_id="test-project")
        return sm, client

    def test_get_single_secret(self) -> None:
        sm, client = self._make_manager()
        response = MagicMock()
        response.payload.data = b"my-secret-value"
        client.access_secret_version.return_value = response
        value = sm.get("SHIOAJI_API_KEY")
        assert value == "my-secret-value"
        client.access_secret_version.assert_called_once_with(
            name="projects/test-project/secrets/SHIOAJI_API_KEY/versions/latest"
        )

    def test_get_with_specific_version(self) -> None:
        sm, client = self._make_manager()
        response = MagicMock()
        response.payload.data = b"v2-value"
        client.access_secret_version.return_value = response
        value = sm.get("SHIOAJI_API_KEY", version="2")
        assert value == "v2-value"
        client.access_secret_version.assert_called_once_with(
            name="projects/test-project/secrets/SHIOAJI_API_KEY/versions/2"
        )


class TestSecretManagerGetBatch:
    def test_batch_retrieval(self) -> None:
        with patch(
            "src.secrets.manager.SecretManagerServiceClient"
        ) as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client
            sm = SecretManager(project_id="test-project")

        def mock_access(name: str) -> MagicMock:
            resp = MagicMock()
            if "API_KEY" in name:
                resp.payload.data = b"key123"
            else:
                resp.payload.data = b"secret456"
            return resp

        client.access_secret_version.side_effect = mock_access
        result = sm.get_batch(["SHIOAJI_API_KEY", "SHIOAJI_SECRET_KEY"])
        assert result == {"SHIOAJI_API_KEY": "key123", "SHIOAJI_SECRET_KEY": "secret456"}
        assert client.access_secret_version.call_count == 2


class TestSecretManagerGetGroup:
    def test_group_resolution(self, tmp_path: Path) -> None:
        f = tmp_path / "secrets.toml"
        f.write_text('[sinopac]\napi_key = "SHIOAJI_API_KEY"\nsecret_key = "SHIOAJI_SECRET_KEY"\n')
        with patch(
            "src.secrets.manager.SecretManagerServiceClient"
        ) as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client
            sm = SecretManager(project_id="test-project")

        response = MagicMock()
        response.payload.data = b"fetched"
        client.access_secret_version.return_value = response
        with patch("src.secrets.manager.load_secret_names") as mock_load:
            mock_load.return_value = {
                "sinopac": {"api_key": "SHIOAJI_API_KEY", "secret_key": "SHIOAJI_SECRET_KEY"}
            }
            result = sm.get_group("sinopac")
        assert result == {"api_key": "fetched", "secret_key": "fetched"}
        assert client.access_secret_version.call_count == 2

    def test_missing_group_raises(self) -> None:
        with patch(
            "src.secrets.manager.SecretManagerServiceClient"
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            sm = SecretManager(project_id="test-project")
        with patch("src.secrets.manager.load_secret_names") as mock_load:
            mock_load.return_value = {"sinopac": {}}
            with pytest.raises(KeyError, match="unknown"):
                sm.get_group("unknown")


class TestSecretManagerCache:
    def test_cache_prevents_duplicate_calls(self) -> None:
        with patch(
            "src.secrets.manager.SecretManagerServiceClient"
        ) as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client
            sm = SecretManager(project_id="test-project")
        response = MagicMock()
        response.payload.data = b"cached-value"
        client.access_secret_version.return_value = response
        v1 = sm.get("MY_SECRET")
        v2 = sm.get("MY_SECRET")
        assert v1 == v2 == "cached-value"
        client.access_secret_version.assert_called_once()


class TestSecretManagerErrors:
    def test_not_found_raises(self) -> None:
        from google.api_core.exceptions import NotFound

        with patch(
            "src.secrets.manager.SecretManagerServiceClient"
        ) as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client
            sm = SecretManager(project_id="test-project")
        client.access_secret_version.side_effect = NotFound("not found")
        with pytest.raises(SecretNotFoundError, match="MISSING_SECRET"):
            sm.get("MISSING_SECRET")

    def test_permission_denied_raises(self) -> None:
        from google.api_core.exceptions import PermissionDenied

        with patch(
            "src.secrets.manager.SecretManagerServiceClient"
        ) as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client
            sm = SecretManager(project_id="test-project")
        client.access_secret_version.side_effect = PermissionDenied("denied")
        with pytest.raises(SecretAccessError, match="permission denied"):
            sm.get("LOCKED_SECRET")


class TestErrorMessages:
    def test_not_found_message(self) -> None:
        err = SecretNotFoundError("MY_SECRET", "my-project")
        assert "MY_SECRET" in str(err)
        assert "my-project" in str(err)
        assert "gcloud secrets create" in str(err)

    def test_access_error_message(self) -> None:
        err = SecretAccessError("MY_SECRET", "my-project", "permission denied")
        assert "MY_SECRET" in str(err)
        assert "secretmanager.secretAccessor" in str(err)
        assert "gcloud auth application-default login" in str(err)
