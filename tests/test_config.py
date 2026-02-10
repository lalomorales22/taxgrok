from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from taxgrok.config import ConfigError, load_runtime_config, resolve_username


class ConfigTests(unittest.TestCase):
    def test_missing_api_key_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with mock.patch.dict(os.environ, {}, clear=True):
                    with self.assertRaises(ConfigError):
                        load_runtime_config()
            finally:
                os.chdir(previous_cwd)

    def test_load_config_with_api_key_and_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.dict(os.environ, {"XAI_API_KEY": "test-key"}, clear=True):
                config = load_runtime_config(
                    username_override="Alice Example",
                    output_dir=tmp_dir,
                )
        self.assertEqual(config.xai_api_key, "test-key")
        self.assertEqual(config.username, "Alice-Example")
        self.assertEqual(config.output_dir, Path(tmp_dir).resolve())
        self.assertEqual(config.xai_base_url, "https://api.x.ai")
        self.assertTrue(config.cleanup_remote_files)
        self.assertFalse(config.refresh_irs_sources)
        self.assertTrue(config.local_redaction)

    def test_resolve_username_from_env(self) -> None:
        with mock.patch.dict(os.environ, {"TAXGROK_USERNAME": "my local user"}, clear=True):
            resolved = resolve_username()
        self.assertEqual(resolved, "my-local-user")

    def test_load_config_from_dotenv_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "XAI_API_KEY=dotenv-key\nTAXGROK_LOCAL_REDACTION=1\n",
                encoding="utf-8",
            )
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with mock.patch.dict(os.environ, {}, clear=True):
                    config = load_runtime_config(output_dir=root)
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(config.xai_api_key, "dotenv-key")
        self.assertTrue(config.local_redaction)

    def test_local_redaction_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.dict(
                os.environ,
                {"XAI_API_KEY": "test-key", "TAXGROK_LOCAL_REDACTION": "0"},
                clear=True,
            ):
                config = load_runtime_config(output_dir=tmp_dir)
        self.assertFalse(config.local_redaction)

    def test_load_config_with_base_url_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.dict(
                os.environ,
                {"XAI_API_KEY": "test-key", "TAXGROK_XAI_BASE_URL": "https://us-east-1.api.x.ai/"},
                clear=True,
            ):
                config = load_runtime_config(output_dir=tmp_dir)
        self.assertEqual(config.xai_base_url, "https://us-east-1.api.x.ai")

    def test_invalid_base_url_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.dict(
                os.environ,
                {"XAI_API_KEY": "test-key", "TAXGROK_XAI_BASE_URL": "api.x.ai"},
                clear=True,
            ):
                with self.assertRaises(ConfigError):
                    load_runtime_config(output_dir=tmp_dir)


if __name__ == "__main__":
    unittest.main()
