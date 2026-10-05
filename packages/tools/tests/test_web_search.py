"""Tests for WebSearchTool and its providers (all HTTP mocked, offline)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from agentforge_tools.web_search import (
    BraveSearchProvider,
    DuckDuckGoProvider,
    SearchResult,
    WebSearchProvider,
    WebSearchTool,
)

# A minimal stand-in for the DuckDuckGo HTML endpoint: two organic results
# (one with the wrapped /l/?uddg= redirect form, one direct), one ad link
# that must be filtered out, and one titleless anchor.
_DDG_HTML = """
<html><body>
<div class="result">
  <a class="result__a"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fchurn-guide&amp;rut=abc">Churn guide</a>
  <a class="result__snippet" href="#">How to reduce churn in three steps and more text.</a>
</div>
<div class="result">
  <a class="result__a" href="https://docs.example.com/metrics">Metrics docs</a>
  <a class="result__snippet" href="#">Definitions of retention metrics.</a>
</div>
<div class="result">
  <a class="result__a" href="https://duckduckgo.com/y.js?ad_domain=ads">Sponsored ad</a>
  <a class="result__snippet" href="#">Buy things!</a>
</div>
<div class="result">
  <a class="result__a" href="https://example.com/empty"></a>
</div>
</body></html>
"""

_BRAVE_JSON: dict[str, Any] = {
    "web": {
        "results": [
            {
                "title": "Brave hit one",
                "url": "https://one.example.com",
                "description": "First brave description.",
            },
            {
                "title": "Brave hit two",
                "url": "https://two.example.com",
                "description": "Second brave description.",
            },
            {"title": "no url", "url": "", "description": "dropped"},
            "not-a-dict",
        ]
    }
}


def _ddg_handler(request: httpx.Request) -> httpx.Response:
    """Mock DDG endpoint: assert request shape, serve the canned HTML."""
    assert request.url.host == "html.duckduckgo.com"
    assert request.url.params["q"]  # query was sent
    assert "agentforge" in request.headers["user-agent"].lower()
    return httpx.Response(200, text=_DDG_HTML)


def _brave_handler(request: httpx.Request) -> httpx.Response:
    """Mock Brave endpoint: assert auth header, serve canned JSON."""
    assert request.url.host == "api.search.brave.com"
    assert request.headers["x-subscription-token"] == "test-key-123"
    return httpx.Response(200, json=_BRAVE_JSON)


# ---------------------------------------------------------------------------
# DuckDuckGoProvider
# ---------------------------------------------------------------------------

class TestDuckDuckGoProvider:
    """Best-effort keyless provider against a mocked HTML endpoint."""

    def test_parses_results_and_unwraps_urls(self) -> None:
        """Titles, snippets and decoded destination URLs come back in order."""
        provider = DuckDuckGoProvider(transport=httpx.MockTransport(_ddg_handler))
        results = provider.search("reduce churn", max_results=10)
        assert [r.title for r in results] == ["Churn guide", "Metrics docs"]
        assert results[0].url == "https://example.com/churn-guide"
        assert results[0].snippet.startswith("How to reduce churn")
        assert results[1].url == "https://docs.example.com/metrics"

    def test_ad_links_filtered(self) -> None:
        """y.js ad links never surface as results."""
        provider = DuckDuckGoProvider(transport=httpx.MockTransport(_ddg_handler))
        results = provider.search("anything", max_results=10)
        assert all("y.js" not in r.url for r in results)

    def test_max_results_clamps(self) -> None:
        """Only max_results hits are returned even when more parse."""
        provider = DuckDuckGoProvider(transport=httpx.MockTransport(_ddg_handler))
        results = provider.search("q", max_results=1)
        assert len(results) == 1

    def test_http_error_raises(self) -> None:
        """Non-200 responses raise (the tool converts to ok=False)."""
        provider = DuckDuckGoProvider(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(403, text="bot challenge")
            )
        )
        with pytest.raises(httpx.HTTPError):
            provider.search("q", max_results=5)

    def test_network_error_raises(self) -> None:
        """Transport-level failures raise httpx.HTTPError subclasses."""
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host", request=request)

        provider = DuckDuckGoProvider(transport=httpx.MockTransport(handler))
        with pytest.raises(httpx.HTTPError):
            provider.search("q", max_results=5)

    def test_markup_change_yields_zero_results_never_fabrication(self) -> None:
        """Unrecognizable markup parses to an empty list -- no invented hits."""
        provider = DuckDuckGoProvider(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text="<html><body>captcha</body></html>")
            )
        )
        assert provider.search("q", max_results=5) == []


# ---------------------------------------------------------------------------
# BraveSearchProvider
# ---------------------------------------------------------------------------

class TestBraveSearchProvider:
    """Brave API provider against a mocked JSON endpoint."""

    def test_parses_brave_results(self) -> None:
        """web.results entries map to SearchResult, junk entries are skipped."""
        provider = BraveSearchProvider(
            api_key="test-key-123", transport=httpx.MockTransport(_brave_handler)
        )
        results = provider.search("saas benchmarks", max_results=5)
        assert [r.title for r in results] == ["Brave hit one", "Brave hit two"]
        assert results[0].url == "https://one.example.com"
        assert results[1].snippet == "Second brave description."

    def test_missing_key_raises(self) -> None:
        """No key anywhere -> immediate, honest failure."""
        provider = BraveSearchProvider(api_key="", transport=httpx.MockTransport(_brave_handler))
        with pytest.raises(RuntimeError, match="BRAVE_API_KEY"):
            provider.search("q", max_results=5)

    def test_reads_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The key falls back to the BRAVE_API_KEY env var."""
        monkeypatch.setenv("BRAVE_API_KEY", "env-key-999")
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["token"] = request.headers["x-subscription-token"]
            return httpx.Response(200, json={"web": {"results": []}})

        provider = BraveSearchProvider(transport=httpx.MockTransport(handler))
        provider.search("q", max_results=3)
        assert captured["token"] == "env-key-999"

    def test_http_error_raises(self) -> None:
        """HTTP failures surface as exceptions (tool converts to ok=False)."""
        provider = BraveSearchProvider(
            api_key="k",
            transport=httpx.MockTransport(lambda request: httpx.Response(429)),
        )
        with pytest.raises(httpx.HTTPError):
            provider.search("q", max_results=5)


# ---------------------------------------------------------------------------
# WebSearchTool
# ---------------------------------------------------------------------------

class _NullProvider(WebSearchProvider):
    """Provider that is never actually called (validation fails first)."""

    name = "null"

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        raise AssertionError("provider must not be called for invalid inputs")


class TestWebSearchTool:
    """Tool-level behavior: inputs, provider selection, error envelope."""

    def _failing_provider(self) -> WebSearchProvider:
        """A provider whose search always raises a transport error."""

        class FailingProvider(WebSearchProvider):
            name = "failing"

            def search(self, query: str, max_results: int) -> list[SearchResult]:
                raise httpx.ConnectError("offline", request=None)  # type: ignore[arg-type]

        return FailingProvider()

    def test_input_validation(self) -> None:
        """Missing/empty/non-string query fails honestly."""
        tool = WebSearchTool(provider=_NullProvider())
        for bad in ({}, {"query": ""}, {"query": 42}, {"query": "   "}):
            result = tool.run(bad)  # type: ignore[arg-type]
            assert result.ok is False, bad
            assert "query" in (result.error or "")

    def test_max_results_type_and_clamp(self) -> None:
        """Bad max_results fails; out-of-range values clamp to [1, 20]."""
        tool = WebSearchTool(provider=_NullProvider())
        assert tool.run({"query": "q", "max_results": "lots"}).ok is False

        class CountingProvider(WebSearchProvider):
            name = "counting"

            def __init__(self) -> None:
                self.seen: int | None = None

            def search(self, query: str, max_results: int) -> list[SearchResult]:
                self.seen = max_results
                return []

        counting = CountingProvider()
        tool2 = WebSearchTool(provider=counting)
        assert tool2.run({"query": "q", "max_results": 999}).ok is True
        assert counting.seen == 20

    def test_network_failure_is_ok_false_with_clear_error(self) -> None:
        """A provider exception becomes ToolResult(ok=False) -- never fabricated data."""
        tool = WebSearchTool(provider=self._failing_provider())
        result = tool.run({"query": "market size"})
        assert result.ok is False
        assert "network error" in (result.error or "")
        assert "failing" in (result.error or "")

    def test_success_shape(self) -> None:
        """Success returns {query, results, provider, count} exactly as pinned."""

        class FakeProvider(WebSearchProvider):
            name = "fake"

            def search(self, query: str, max_results: int) -> list[SearchResult]:
                return [
                    SearchResult(
                        title="T", url="https://example.com", snippet="s"
                    )
                ]

        result = WebSearchTool(provider=FakeProvider()).run({"query": "q"})
        assert result.ok is True
        assert result.data is not None
        assert result.data["query"] == "q"
        assert result.data["provider"] == "fake"
        assert result.data["count"] == 1
        assert result.data["results"] == [
            {"title": "T", "url": "https://example.com", "snippet": "s"}
        ]

    def test_ddg_provider_selected_without_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No BRAVE_API_KEY -> DuckDuckGo provider, and a best-effort note."""
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        tool = WebSearchTool()
        assert tool.provider_name == "duckduckgo"

    def test_brave_provider_selected_with_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BRAVE_API_KEY set -> Brave provider wins automatically."""
        monkeypatch.setenv("BRAVE_API_KEY", "abc")
        tool = WebSearchTool()
        assert tool.provider_name == "brave"

    def test_mocked_ddg_end_to_end(self) -> None:
        """Full tool path over the mocked DDG endpoint (offline)."""
        tool = WebSearchTool(
            provider=DuckDuckGoProvider(transport=httpx.MockTransport(_ddg_handler))
        )
        result = tool.run({"query": "reduce churn", "max_results": 2})
        assert result.ok is True
        assert result.data is not None
        assert result.data["provider"] == "duckduckgo"
        assert result.data["count"] == 2
        assert result.data["note"]  # best-effort disclaimer present
        first = result.data["results"][0]
        assert first["url"] == "https://example.com/churn-guide"

    def test_mocked_brave_end_to_end(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Full tool path over the mocked Brave endpoint (offline)."""
        monkeypatch.setenv("BRAVE_API_KEY", "test-key-123")
        tool = WebSearchTool(
            provider=BraveSearchProvider(
                api_key="test-key-123", transport=httpx.MockTransport(_brave_handler)
            )
        )
        result = tool.run({"query": "benchmarks", "max_results": 5})
        assert result.ok is True
        assert result.data is not None
        assert result.data["provider"] == "brave"
        assert result.data["count"] == 2
        assert result.data.get("note") is None
