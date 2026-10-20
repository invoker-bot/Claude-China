from contextlib import contextmanager
from pathlib import Path
import shutil
import os
from unittest.mock import patch
from uuid import uuid4

from src.claude_china.config import load_config, save_config
from src.claude_china.profiles import add_profile, list_profiles, show_profile, remove_profile
from src.claude_china.models import profile_from_dict, ApiProfile, LoginProfile
from src.claude_china.launcher import prepare_environment


@contextmanager
def temp_config_file():
    root = Path.cwd() / ".test-artifacts" / str(uuid4())
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root / "config.yaml"
    finally:
        shutil.rmtree(root, ignore_errors=True)


class TestFullWorkflowApiProfile:
    """Test complete workflow for API profile (Claude)"""

    def test_full_workflow_api_profile(self):
        """Test full workflow: add API profile -> show -> list -> remove"""
        with temp_config_file() as config_file:
            with patch("src.claude_china.config.CONFIG_FILE", config_file):
                config = {"profiles": {}}
                save_config(config)

                inputs = [
                    "my-claude-api",
                    "claude",
                    "api",
                    "https://api.anthropic.com",
                    "sk-ant-test-token",
                    "",   # proxy
                    "",   # default_args
                ]

                with patch("builtins.input", side_effect=inputs):
                    config = load_config()
                    config = add_profile(config)
                    save_config(config)

                config = load_config()
                assert "my-claude-api" in config["profiles"]
                profile_dict = config["profiles"]["my-claude-api"]
                assert profile_dict["name"] == "my-claude-api"
                assert profile_dict["type"] == "claude"
                assert profile_dict["mode"] == "api"
                assert profile_dict["base_url"] == "https://api.anthropic.com"
                assert profile_dict["token"] == "sk-ant-test-token"

                profile = profile_from_dict(profile_dict)
                assert isinstance(profile, ApiProfile)
                assert profile.name == "my-claude-api"
                assert profile.type == "claude"

                env = prepare_environment(profile)
                assert env["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com"
                assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-ant-test-token"

                with patch("builtins.print") as mock_print:
                    show_profile(config, "my-claude-api")
                    assert mock_print.called

                with patch("builtins.print") as mock_print:
                    list_profiles(config)
                    assert mock_print.called

                config = remove_profile(config, "my-claude-api")
                assert "my-claude-api" not in config["profiles"]

    def test_blank_base_url_defaults_to_official_claude(self):
        with temp_config_file() as config_file:
            with patch("src.claude_china.config.CONFIG_FILE", config_file):
                save_config({"profiles": {}})
                inputs = [
                    "official-claude",
                    "claude",
                    "api",
                    "",  # official Anthropic endpoint
                    "sk-ant-test-token",
                    "",  # proxy
                    "",  # default_args
                ]

                with patch("builtins.input", side_effect=inputs):
                    config = add_profile(load_config())
                    save_config(config)

                profile_dict = load_config()["profiles"]["official-claude"]
                assert profile_dict["base_url"] == "https://api.anthropic.com"
                env = prepare_environment(profile_from_dict(profile_dict))
                assert env["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com"
                assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-ant-test-token"


class TestFullWorkflowLoginProfile:
    """Test complete workflow for login profile (Claude)"""

    def test_full_workflow_login_profile(self):
        """Test full workflow: add login profile -> show -> list -> remove"""
        with temp_config_file() as config_file:
            with patch("src.claude_china.config.CONFIG_FILE", config_file):
                config = {"profiles": {}}
                save_config(config)

                inputs = [
                    "my-claude-login",
                    "claude",
                    "login",
                    "~/.claude-profiles/account-a",
                    "http://127.0.0.1:7890",
                    "",   # default_args
                ]

                with patch("builtins.input", side_effect=inputs):
                    config = load_config()
                    config = add_profile(config)
                    save_config(config)

                config = load_config()
                assert "my-claude-login" in config["profiles"]
                profile_dict = config["profiles"]["my-claude-login"]
                assert profile_dict["name"] == "my-claude-login"
                assert profile_dict["type"] == "claude"
                assert profile_dict["mode"] == "login"
                assert profile_dict["credentials_path"] == "~/.claude-profiles/account-a"
                assert profile_dict["proxy"] == "http://127.0.0.1:7890"

                profile = profile_from_dict(profile_dict)
                assert isinstance(profile, LoginProfile)
                assert profile.name == "my-claude-login"
                assert profile.type == "claude"

                env = prepare_environment(profile)
                assert "ANTHROPIC_BASE_URL" not in env
                assert "ANTHROPIC_AUTH_TOKEN" not in env
                assert env["CLAUDE_CONFIG_DIR"] == os.path.expanduser("~/.claude-profiles/account-a")
                assert env["HTTP_PROXY"] == "http://127.0.0.1:7890"
                assert env["HTTPS_PROXY"] == "http://127.0.0.1:7890"

                with patch("builtins.print") as mock_print:
                    show_profile(config, "my-claude-login")
                    assert mock_print.called

                with patch("builtins.print") as mock_print:
                    list_profiles(config)
                    assert mock_print.called

                config = remove_profile(config, "my-claude-login")
                assert "my-claude-login" not in config["profiles"]


class TestBackwardCompatibility:
    """Test backward compatibility with legacy profiles"""

    def test_backward_compatibility(self):
        """Test that legacy profiles without name/mode still work and are migrated"""
        with temp_config_file() as config_file:
            with patch("src.claude_china.config.CONFIG_FILE", config_file):
                legacy_config = {
                    "profiles": {
                        "legacy-claude": {
                            "type": "claude",
                            "base_url": "https://api.anthropic.com",
                            "token": "sk-ant-legacy-token",
                        }
                    }
                }
                save_config(legacy_config)

                config = load_config()
                assert "legacy-claude" in config["profiles"]
                profile_dict = config["profiles"]["legacy-claude"]
                assert profile_dict["name"] == "legacy-claude"
                assert profile_dict["mode"] == "api"

                profile = profile_from_dict(profile_dict)
                assert isinstance(profile, ApiProfile)
                assert profile.name == "legacy-claude"
                assert profile.base_url == "https://api.anthropic.com"
                assert profile.token == "sk-ant-legacy-token"

                env = prepare_environment(profile)
                assert env["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com"
                assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-ant-legacy-token"

                with patch("builtins.print") as mock_print:
                    show_profile(config, "legacy-claude")
                    assert mock_print.called

                with patch("builtins.print") as mock_print:
                    list_profiles(config)
                    assert mock_print.called

class TestCodexProfiles:
    """Test codex profile workflows"""

    def test_codex_api_profile(self):
        """Test codex API mode profile"""
        with temp_config_file() as config_file:
            with patch("src.claude_china.config.CONFIG_FILE", config_file):
                config = {"profiles": {}}
                save_config(config)

                inputs = [
                    "my-codex-api",
                    "codex",
                    "api",
                    "https://api.openai.com/v1",
                    "sk-test-key",
                    "",   # proxy
                    "",   # default_args
                ]

                with patch("builtins.input", side_effect=inputs):
                    config = load_config()
                    config = add_profile(config)
                    save_config(config)

                config = load_config()
                assert "my-codex-api" in config["profiles"]
                profile_dict = config["profiles"]["my-codex-api"]
                assert profile_dict["name"] == "my-codex-api"
                assert profile_dict["type"] == "codex"
                assert profile_dict["mode"] == "api"

                profile = profile_from_dict(profile_dict)
                assert isinstance(profile, ApiProfile)
                assert profile.name == "my-codex-api"
                assert profile.type == "codex"

                env = prepare_environment(profile)
                assert env["OPENAI_API_KEY"] == "sk-test-key"
                assert env["OPENAI_BASE_URL"] == "https://api.openai.com/v1"

    def test_blank_base_url_defaults_to_official_codex(self):
        with temp_config_file() as config_file:
            with patch("src.claude_china.config.CONFIG_FILE", config_file):
                save_config({"profiles": {}})
                inputs = [
                    "official-codex",
                    "codex",
                    "api",
                    "",  # official OpenAI endpoint
                    "sk-test-key",
                    "",  # proxy
                    "",  # default_args
                ]

                with patch("builtins.input", side_effect=inputs):
                    config = add_profile(load_config())
                    save_config(config)

                profile_dict = load_config()["profiles"]["official-codex"]
                assert profile_dict["base_url"] == "https://api.openai.com/v1"
                env = prepare_environment(profile_from_dict(profile_dict))
                assert env["OPENAI_BASE_URL"] == "https://api.openai.com/v1"
                assert env["OPENAI_API_KEY"] == "sk-test-key"

    def test_add_profile_captures_default_args(self):
        """`claudec add` records non-empty default_args as a string in YAML."""
        with temp_config_file() as config_file:
            with patch("src.claude_china.config.CONFIG_FILE", config_file):
                save_config({"profiles": {}})

                inputs = [
                    "with-defaults",
                    "claude",
                    "api",
                    "https://api.anthropic.com",
                    "sk-ant-test",
                    "",                                  # proxy
                    "--model claude-opus-4-5 -p hi",     # default_args
                ]

                with patch("builtins.input", side_effect=inputs):
                    config = load_config()
                    config = add_profile(config)
                    save_config(config)

                config = load_config()
                profile_dict = config["profiles"]["with-defaults"]
                assert profile_dict["default_args"] == "--model claude-opus-4-5 -p hi"

    def test_codex_login_profile(self):
        """Test codex login mode profile"""
        with temp_config_file() as config_file:
            with patch("src.claude_china.config.CONFIG_FILE", config_file):
                config = {"profiles": {}}
                save_config(config)

                inputs = [
                    "my-codex-login",
                    "codex",
                    "login",
                    "~/.codex-profiles/account-a",
                    "",   # proxy
                    "",   # default_args
                ]

                with patch("builtins.input", side_effect=inputs):
                    config = load_config()
                    config = add_profile(config)
                    save_config(config)

                config = load_config()
                assert "my-codex-login" in config["profiles"]
                profile_dict = config["profiles"]["my-codex-login"]
                assert profile_dict["name"] == "my-codex-login"
                assert profile_dict["type"] == "codex"
                assert profile_dict["mode"] == "login"
                assert profile_dict["credentials_path"] == "~/.codex-profiles/account-a"

                profile = profile_from_dict(profile_dict)
                assert isinstance(profile, LoginProfile)
                assert profile.name == "my-codex-login"
                assert profile.type == "codex"

                env = prepare_environment(profile)
                assert "OPENAI_API_KEY" not in env
                assert env["CODEX_HOME"] == os.path.expanduser("~/.codex-profiles/account-a")


class TestGrokProfiles:
    """Test official Grok CLI profile workflows."""

    def test_grok_api_profile(self):
        with temp_config_file() as config_file:
            with patch("src.claude_china.config.CONFIG_FILE", config_file):
                save_config({"profiles": {}})
                inputs = [
                    "my-grok-api",
                    "grok",
                    "api",
                    "",  # official xAI endpoint
                    "xai-test-key",
                    "",  # proxy
                    "",  # default_args
                ]

                with patch("builtins.input", side_effect=inputs):
                    config = add_profile(load_config())
                    save_config(config)

                profile_dict = load_config()["profiles"]["my-grok-api"]
                assert profile_dict["type"] == "grok"
                assert profile_dict["mode"] == "api"
                assert profile_dict["base_url"] == "https://api.x.ai/v1"
                assert profile_dict["api_key"] == "xai-test-key"

                env = prepare_environment(profile_from_dict(profile_dict))
                assert env["XAI_API_KEY"] == "xai-test-key"
                assert "GROK_CLI_CHAT_PROXY_BASE_URL" not in env

    def test_grok_login_profile(self):
        with temp_config_file() as config_file:
            with patch("src.claude_china.config.CONFIG_FILE", config_file):
                save_config({"profiles": {}})
                inputs = [
                    "my-grok-login",
                    "grok",
                    "login",
                    "~/.grok-profiles/account-a",
                    "",  # proxy
                    "",  # default_args
                ]

                with patch("builtins.input", side_effect=inputs):
                    config = add_profile(load_config())
                    save_config(config)

                profile_dict = load_config()["profiles"]["my-grok-login"]
                assert profile_dict["type"] == "grok"
                assert profile_dict["mode"] == "login"

                env = prepare_environment(profile_from_dict(profile_dict))
                assert env["GROK_HOME"] == os.path.expanduser(
                    "~/.grok-profiles/account-a"
                )
                assert "XAI_API_KEY" not in env
