from dataclasses import dataclass
from typing import Mapping, Tuple


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    display: str
    command: str
    official_base_url: str
    env: Mapping[str, str]
    secret_field: str
    config_dir_env: str = ""
    auth_modes: Tuple[str, ...] = ("api", "login")
    npm_package: str = ""
    desktop_app_id: str = ""
    history_home: str = ""
    resume_prefix: Tuple[str, ...] = ()
    managed_env: Tuple[str, ...] = ()
    native_upgrade: str = ""
    settings_provider: str = ""


PROVIDERS = (
    ProviderSpec(
        id="claude",
        display="Claude Code",
        command="claude",
        official_base_url="https://api.anthropic.com",
        env={"ANTHROPIC_BASE_URL": "base_url", "ANTHROPIC_AUTH_TOKEN": "token"},
        secret_field="token",
        config_dir_env="CLAUDE_CONFIG_DIR",
        npm_package="@anthropic-ai/claude-code",
        desktop_app_id="claude",
        history_home=".claude",
        resume_prefix=("--resume",),
    ),
    ProviderSpec(
        id="grok",
        display="Grok CLI",
        command="grok",
        official_base_url="https://api.x.ai/v1",
        env={"GROK_CLI_CHAT_PROXY_BASE_URL": "base_url", "XAI_API_KEY": "api_key"},
        secret_field="api_key",
        config_dir_env="GROK_HOME",
        npm_package="@xai-official/grok",
        desktop_app_id="grok-bot",
        history_home=".grok",
        resume_prefix=("--resume",),
    ),
    ProviderSpec(
        id="codex",
        display="Codex CLI",
        command="codex",
        official_base_url="https://api.openai.com/v1",
        env={"OPENAI_BASE_URL": "base_url", "OPENAI_API_KEY": "api_key"},
        secret_field="api_key",
        config_dir_env="CODEX_HOME",
        npm_package="@openai/codex",
        desktop_app_id="codex",
        history_home=".codex",
        resume_prefix=("resume",),
    ),
    ProviderSpec(
        id="antigravity",
        display="Antigravity CLI",
        command="agy",
        official_base_url="",
        env={"GOOGLE_GEMINI_BASE_URL": "base_url", "GEMINI_API_KEY": "api_key"},
        secret_field="api_key",
        auth_modes=("api",),
        desktop_app_id="antigravity",
        managed_env=("AGY_ADC_AUTH",),
        native_upgrade="https://antigravity.google/cli/install",
        settings_provider="gemini",
    ),
)

_BY_ID = {provider.id: provider for provider in PROVIDERS}


def get_provider(kind):
    try:
        return _BY_ID[kind]
    except KeyError:
        raise ValueError(f"Unknown profile type '{kind}'") from None


def provider_ids():
    return tuple(provider.id for provider in PROVIDERS)


def safety_app_id(kind):
    return get_provider(kind).desktop_app_id
