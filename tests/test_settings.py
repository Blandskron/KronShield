import pytest

from core import settings
from domain.budget import BudgetLimits


@pytest.fixture
def configuration_file(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    monkeypatch.setattr(settings, "CONFIG_PATH", path)
    settings.configuration.cache_clear()
    yield path
    settings.configuration.cache_clear()


def test_configuration_validates_yaml_and_keeps_defaults_for_omitted_fields(configuration_file, monkeypatch):
    configuration_file.write_text(
        "timeouts:\n  request: 2.5\nports_to_scan: [443, 8443]\nexecution:\n  burst: 3\n"
        "llm:\n  temperature: 0.5\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-20b")

    config = settings.configuration()
    assert isinstance(config.execution, BudgetLimits)
    assert config.execution.burst == 3
    assert config.execution.max_operations == BudgetLimits().max_operations
    assert settings.request_timeout() == 2.5
    assert settings.ports_to_scan() == [443, 8443]
    assert settings.llm()["model"] == "openai/gpt-oss-20b"
    assert settings.llm()["temperature"] == 0.5
    assert config.llm.model == "openai/gpt-oss-120b"
    legacy = settings.load()
    legacy["ports_to_scan"].append(80)
    assert settings.load()["ports_to_scan"] == [443, 8443]


@pytest.mark.parametrize("yaml_settings", [
    "- not-a-mapping",
    "unknown: 1",
    "ports_to_scan: [true]",
    "ports_to_scan: ['443']",
    "ports_to_scan: [0, 65536]",
    "ports_to_scan: [443, 443]",
    "timeouts: {request: .inf}",
    "timeouts: {request: -5}",
    "timeouts: {request: 121}",
    "execution: {max_operations: 0}",
    "execution: {max_bytes: '1024'}",
    "execution: {operations_per_second: .nan}",
    "execution: {burst: true}",
    "execution: {max_concurrent: 33}",
    "llm: {provider: unknown}",
    "llm: {temperature: 3}",
    "xss_payloads: 'not-a-list'",
    "sqli_payloads: [42]",
    "execution: {burst: 1, burst: 2}",
    "execution: [",
])
def test_invalid_configuration_fails_at_load_time(configuration_file, yaml_settings):
    configuration_file.write_text(yaml_settings, encoding="utf-8")
    with pytest.raises(ValueError):
        settings.configuration()


def test_invalid_model_override_is_validated_without_echoing_its_value(configuration_file, monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "secret text")
    with pytest.raises(ValueError) as error:
        settings.llm()
    assert "secret text" not in str(error.value)


def test_configuration_resolves_user_file_and_explicit_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PENTEST_AGENT_CONFIG", raising=False)
    for variable in ("APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(variable, str(tmp_path / "user"))

    user_settings = tmp_path / "user" / "pentest-agent" / "config.yaml"
    assert settings.configuration_path() == user_settings

    workspace_settings = tmp_path / "config" / "config.yaml"
    workspace_settings.parent.mkdir()
    workspace_settings.touch()
    assert settings.configuration_path().resolve() == workspace_settings

    explicit = tmp_path / "explicit.yaml"
    monkeypatch.setenv("PENTEST_AGENT_CONFIG", str(explicit))
    assert settings.configuration_path() == explicit


def test_missing_explicit_configuration_fails_closed(configuration_file, monkeypatch):
    monkeypatch.setenv("PENTEST_AGENT_CONFIG", str(configuration_file))
    with pytest.raises(ValueError, match="PENTEST_AGENT_CONFIG points to a missing file"):
        settings.configuration()
