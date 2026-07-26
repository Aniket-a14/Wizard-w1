"""Provider resolution, LM Studio discovery and per-role backend routing.

The invariant these protect: *which* backend a call goes to is a property of the
request, not of the process. Every helper here is exercised without touching a
network -- the HTTP layer is stubbed at ``_get_json``.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.config import PROVIDERS, settings
from src.core.llm import LLMRole, llm_provider
from src.core.llm.registry import ModelRegistry, classify


# --------------------------------------------------------------------------- #
# Settings-level resolution
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", PROVIDERS)
def test_every_declared_provider_resolves_to_itself(name: str) -> None:
    assert settings.resolve_provider(name) == name


@pytest.mark.parametrize("value", ["", None, "   ", "not-a-provider", "OLLAMA_TYPO"])
def test_unknown_provider_falls_back_to_the_configured_default(value: str | None) -> None:
    assert settings.resolve_provider(value) == settings.API_PROVIDER


def test_provider_lookup_is_case_insensitive() -> None:
    assert settings.resolve_provider("LMStudio") == "lmstudio"


@pytest.mark.parametrize(
    "configured",
    ["http://localhost:1234", "http://localhost:1234/", "http://localhost:1234/v1", "http://localhost:1234/v1/"],
)
def test_lmstudio_url_is_normalised_to_a_bare_root(monkeypatch: pytest.MonkeyPatch, configured: str) -> None:
    """LM Studio's own UI shows the `/v1` form, so people paste that."""
    monkeypatch.setattr(settings, "LMSTUDIO_BASE_URL", settings.__class__._normalize_lmstudio_url(configured))
    assert settings.provider_root_url("lmstudio") == "http://localhost:1234"


def test_lmstudio_inference_url_carries_the_v1_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LMSTUDIO_BASE_URL", "http://localhost:1234")
    assert settings.provider_openai_base_url("lmstudio") == "http://localhost:1234/v1"


def test_gateway_url_is_used_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hand-configured gateway already includes its version segment."""
    monkeypatch.setattr(settings, "GATEWAY_API_URL", "https://gateway.example/v1")
    assert settings.provider_openai_base_url("custom_gateway") == "https://gateway.example/v1"


def test_api_keys_are_kept_per_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LMSTUDIO_API_KEY", "lms-key")
    monkeypatch.setattr(settings, "GATEWAY_API_KEY", "gw-key")
    assert settings.provider_api_key("lmstudio") == "lms-key"
    assert settings.provider_api_key("custom_gateway") == "gw-key"


def test_local_providers_are_configured_without_a_gateway_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GATEWAY_API_URL", "")
    assert settings.provider_is_configured("ollama") is True
    assert settings.provider_is_configured("lmstudio") is True
    assert settings.provider_is_configured("custom_gateway") is False


# --------------------------------------------------------------------------- #
# ModelSpec
# --------------------------------------------------------------------------- #
def test_resolve_targets_the_requested_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LMSTUDIO_BASE_URL", "http://localhost:1234")
    spec = llm_provider.resolve(LLMRole.WORKER, model="qwen-coder", provider="lmstudio")
    assert spec.provider == "lmstudio"
    assert spec.base_url == "http://localhost:1234/v1"


def test_resolve_without_a_provider_uses_the_default() -> None:
    spec = llm_provider.resolve(LLMRole.MANAGER)
    assert spec.provider == settings.API_PROVIDER


def test_ollama_spec_points_at_the_bare_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """ChatOllama builds its own paths; handing it a `/v1` base would break it."""
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")
    spec = llm_provider.resolve(LLMRole.MANAGER, provider="ollama")
    assert spec.base_url == "http://localhost:11434"


def test_same_model_name_on_two_providers_has_distinct_cache_keys() -> None:
    """Otherwise the first backend used would answer for the second one too."""
    first = llm_provider.resolve(LLMRole.WORKER, model="qwen2.5-coder", provider="ollama")
    second = llm_provider.resolve(LLMRole.WORKER, model="qwen2.5-coder", provider="lmstudio")
    assert first.cache_key() != second.cache_key()


def test_unavailable_message_names_the_endpoint() -> None:
    """'No client available' with no host is not actionable for a local daemon."""
    spec = llm_provider.resolve(LLMRole.WORKER, model="mystery", provider="lmstudio")
    message = llm_provider._unavailable_message(spec)
    assert "lmstudio" in message and spec.base_url in message and "mystery" in message


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
LMSTUDIO_NATIVE_PAYLOAD: dict[str, Any] = {
    "data": [
        {
            "id": "qwen2.5-coder-7b-instruct",
            "type": "llm",
            "arch": "qwen2",
            "quantization": "Q4_K_M",
            "state": "loaded",
            "max_context_length": 32768,
        },
        {
            "id": "llava-v1.5-7b",
            "type": "vlm",
            "arch": "llama",
            "quantization": "Q4_0",
            "state": "not-loaded",
            "max_context_length": 4096,
        },
        {
            "id": "text-embedding-nomic-embed-text-v1.5",
            "type": "embeddings",
            "arch": "nomic-bert",
            "state": "not-loaded",
        },
    ]
}


def _registry_returning(payloads: dict[str, Any]) -> ModelRegistry:
    """A registry whose HTTP layer answers from a URL->payload map."""
    registry = ModelRegistry()
    calls: list[str] = []

    def fake_get(provider: str, url: str, headers: dict[str, str] | None = None):
        calls.append(url)
        payload = payloads.get(url)
        if payload is None:
            registry._errors[provider] = f"Could not reach {provider} at {url}: refused"
        return payload

    registry._get_json = fake_get  # type: ignore[assignment]
    registry.calls = calls  # type: ignore[attr-defined]
    return registry


def test_lmstudio_native_metadata_beats_name_guessing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LMSTUDIO_BASE_URL", "http://lms:1234")
    registry = _registry_returning({"http://lms:1234/api/v0/models": LMSTUDIO_NATIVE_PAYLOAD})

    models = {m.name: m for m in registry.list_models(provider="lmstudio")}

    coder = models["qwen2.5-coder-7b-instruct"]
    assert "code" in coder.capabilities  # name-derived hint merged in
    assert "chat" in coder.capabilities
    assert coder.quantization == "Q4_K_M"
    assert coder.context_length == 32768
    assert coder.loaded is True
    assert coder.provider == "lmstudio"

    # `type: vlm` is authoritative, not the substring match on the name.
    assert "vision" in models["llava-v1.5-7b"].capabilities
    assert models["llava-v1.5-7b"].loaded is False

    # An embedding model must never be offered as a chat model.
    assert models["text-embedding-nomic-embed-text-v1.5"].capabilities == ["embedding"]


def test_lmstudio_falls_back_to_the_openai_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anything else serving that port speaks `/v1` but not `/api/v0`."""
    monkeypatch.setattr(settings, "LMSTUDIO_BASE_URL", "http://lms:1234")
    registry = _registry_returning({"http://lms:1234/v1/models": {"data": [{"id": "some-model"}]}})

    models = registry.list_models(provider="lmstudio")

    assert [m.name for m in models] == ["some-model"]
    assert registry.calls == ["http://lms:1234/api/v0/models", "http://lms:1234/v1/models"]  # type: ignore[attr-defined]


def test_both_lmstudio_routes_failing_reports_the_native_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LMSTUDIO_BASE_URL", "http://lms:1234")
    registry = _registry_returning({})

    assert registry.list_models(provider="lmstudio") == []
    error = registry.error_for("lmstudio")
    assert error is not None and "api/v0/models" in error


def test_provider_lists_do_not_evict_each_other(monkeypatch: pytest.MonkeyPatch) -> None:
    """A session may run its manager and worker on different backends."""
    monkeypatch.setattr(settings, "LMSTUDIO_BASE_URL", "http://lms:1234")
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://ollama:11434")
    registry = _registry_returning(
        {
            "http://lms:1234/api/v0/models": LMSTUDIO_NATIVE_PAYLOAD,
            "http://ollama:11434/api/tags": {"models": [{"name": "deepseek-r1:1.5b", "size": 1_100_000_000}]},
        }
    )

    registry.list_models(provider="lmstudio")
    registry.list_models(provider="ollama")

    assert [m.name for m in registry.list_models(provider="ollama")] == ["deepseek-r1:1.5b"]
    assert len(registry.list_models(provider="lmstudio")) == 3


def test_errors_are_tracked_per_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://ollama:11434")
    registry = _registry_returning(
        {"http://ollama:11434/api/tags": {"models": [{"name": "deepseek-r1:1.5b"}]}},
    )

    registry.list_models(provider="ollama")
    registry.list_models(provider="lmstudio")

    assert registry.error_for("ollama") is None
    assert registry.error_for("lmstudio") is not None


def test_available_providers_makes_no_network_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """It renders on every page load; an offline host must not add a timeout."""
    registry = _registry_returning({})

    listed = registry.available_providers()

    assert registry.calls == []  # type: ignore[attr-defined]
    assert {entry["id"] for entry in listed} == set(PROVIDERS)
    assert sum(1 for entry in listed if entry["is_default"]) == 1


def test_suggestion_ignores_a_default_that_belongs_to_another_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """`deepseek-r1:1.5b` is an Ollama tag; sending it to LM Studio is a 404."""
    monkeypatch.setattr(settings, "LMSTUDIO_BASE_URL", "http://lms:1234")
    monkeypatch.setattr(settings, "MODEL_NAME", "deepseek-r1:1.5b")
    registry = _registry_returning({"http://lms:1234/api/v0/models": LMSTUDIO_NATIVE_PAYLOAD})

    suggested = registry.suggest(provider="lmstudio")

    assert suggested["manager"] != "deepseek-r1:1.5b"
    assert suggested["manager"] in {m.name for m in registry.list_models(provider="lmstudio")}
    assert suggested["worker"] == "qwen2.5-coder-7b-instruct"
    assert suggested["vision"] == "llava-v1.5-7b"


def test_ollama_discovery_still_reports_its_own_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://ollama:11434")
    registry = _registry_returning(
        {
            "http://ollama:11434/api/tags": {
                "models": [
                    {
                        "name": "qwen2.5-coder:1.5b",
                        "size": 986_000_000,
                        "details": {"family": "qwen2", "parameter_size": "1.5B", "quantization_level": "Q4_K_M"},
                    }
                ]
            }
        }
    )

    (model,) = registry.list_models(provider="ollama")

    assert model.parameter_size == "1.5B"
    assert model.provider == "ollama"
    # Ollama does not report load state, so it must stay unknown rather than False.
    assert model.loaded is None


def test_classify_still_guesses_when_metadata_is_absent() -> None:
    assert "code" in classify("qwen2.5-coder-7b")
    assert classify("nomic-embed-text") == ["embedding"]


def test_a_failed_lookup_is_cached_briefly(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refused TCP connect costs seconds on Windows, and one page load asks
    for both the list and a suggestion. Re-probing an offline provider each
    time made a switched-off backend visibly slow.
    """
    monkeypatch.setattr(settings, "LMSTUDIO_BASE_URL", "http://lms:1234")
    registry = _registry_returning({})

    assert registry.list_models(provider="lmstudio") == []
    probes_after_first = len(registry.calls)  # type: ignore[attr-defined]
    assert registry.list_models(provider="lmstudio") == []

    assert len(registry.calls) == probes_after_first  # type: ignore[attr-defined]


def test_refresh_bypasses_the_failure_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "I just started LM Studio, refresh" has to work without waiting out a TTL."""
    monkeypatch.setattr(settings, "LMSTUDIO_BASE_URL", "http://lms:1234")
    payloads: dict[str, Any] = {}
    registry = _registry_returning(payloads)

    assert registry.list_models(provider="lmstudio") == []

    payloads["http://lms:1234/api/v0/models"] = LMSTUDIO_NATIVE_PAYLOAD
    assert registry.list_models(provider="lmstudio") == []  # still cached
    assert len(registry.list_models(force=True, provider="lmstudio")) == 3
