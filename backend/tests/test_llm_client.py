import pytest

from app.config import settings
from app.services.cloud_llm_client import ChainedLLMClient
from app.services.llm_client import _build_cloud_providers, get_default_llm_client

# conftest.py's autouse _stub_ollama_by_default fixture already clears all
# three provider-key settings before every test, regardless of what's in a
# developer's local .env — each test below only needs to set the keys it's
# specifically testing.


class TestBuildCloudProviders:
    def test_no_keys_configured_returns_no_providers(self) -> None:
        assert _build_cloud_providers() == []

    def test_single_key_produces_one_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "cerebras_api_keys", ("key1",))
        providers = _build_cloud_providers()
        assert len(providers) == 1
        assert providers[0].name == "cerebras#1"

    def test_two_keys_for_one_provider_produce_two_entries_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "cerebras_api_keys", ("key1", "key2"))
        providers = _build_cloud_providers()
        assert [p.name for p in providers] == ["cerebras#1", "cerebras#2"]

    def test_providers_ordered_cerebras_then_groq_then_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "cerebras_api_keys", ("c1",))
        monkeypatch.setattr(settings, "groq_api_keys", ("g1",))
        monkeypatch.setattr(settings, "gemini_api_keys", ("m1",))
        providers = _build_cloud_providers()
        assert [p.name for p in providers] == ["cerebras#1", "groq#1", "gemini#1"]

    def test_a_providers_own_keys_are_tried_before_moving_to_the_next_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "cerebras_api_keys", ("c1", "c2"))
        monkeypatch.setattr(settings, "groq_api_keys", ("g1",))
        providers = _build_cloud_providers()
        assert [p.name for p in providers] == ["cerebras#1", "cerebras#2", "groq#1"]

    def test_blank_key_in_the_list_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "cerebras_api_keys", ("key1", "", "key2"))
        providers = _build_cloud_providers()
        # Only 2 usable providers — the blank slot is skipped. Naming keeps
        # each provider's original configured position (#1, #3) rather than
        # renumbering sequentially, so a log message about "cerebras#3"
        # still maps directly to the 3rd key a user configured.
        assert [p.name for p in providers] == ["cerebras#1", "cerebras#3"]


class TestGetDefaultLlmClient:
    def test_no_keys_falls_back_to_ollama_not_the_cloud_chain(self) -> None:
        # Can't assert isinstance(client, OllamaClient) here: conftest's
        # autouse stub replaces OllamaClient itself with a test double for
        # every test not marked real_ollama, so the real class never gets
        # constructed in this suite. Asserting the cloud chain was NOT
        # chosen still proves the no-keys branch took the fallback path.
        client = get_default_llm_client()
        assert not isinstance(client, ChainedLLMClient)

    def test_any_key_configured_returns_the_cloud_chain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "cerebras_api_keys", ("key1",))
        client = get_default_llm_client()
        assert isinstance(client, ChainedLLMClient)
