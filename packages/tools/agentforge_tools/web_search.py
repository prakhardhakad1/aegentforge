"""Web search tool with pluggable providers (DuckDuckGo HTML, Brave API).

The tool never fabricates results: if the network call or parsing fails, it
returns ``ToolResult(ok=False, error=...)``. The DuckDuckGo provider queries a
public HTML endpoint with no API key -- this is **best-effort**: DuckDuckGo may
change its markup or rate-limit unauthenticated traffic, in which case the
provider either returns fewer results or signals failure. Set ``BRAVE_API_KEY``
to use the (more reliable) Brave Search API instead; the tool picks Brave
automatically when the env var is present.

Both providers accept an ``httpx`` ``transport`` so tests can inject
``httpx.MockTransport`` and run fully offline.
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

from agentforge_tools.base import Tool, ToolResult

__all__ = [
    "SearchResult",
    "WebSearchProvider",
    "DuckDuckGoProvider",
    "BraveSearchProvider",
    "WebSearchTool",
]

_DEFAULT_TIMEOUT_SECONDS = 10.0
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) AgentForge/0.1 (hackathon project) Firefox/126.0"
)


@dataclass
class SearchResult:
    """A single web search hit."""

    title: str
    url: str
    snippet: str

    def to_dict(self) -> dict[str, str]:
        """JSON-serializable representation."""
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class WebSearchProvider(ABC):
    """Interface for web-search backends."""

    name: str = "provider"

    @abstractmethod
    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Run ``query`` and return up to ``max_results`` results.

        Implementations should raise an exception on transport/parsing
        failure; :class:`WebSearchTool` converts that into an error result.
        """
        raise NotImplementedError  # pragma: no cover


# ---------------------------------------------------------------------------
# DuckDuckGo (no API key, best-effort HTML scraping)
# ---------------------------------------------------------------------------

class _DDGResultParser(HTMLParser):
    """Extract result titles/links/snippets from the DDG HTML endpoint.

    The endpoint wraps outbound links in ``/l/?uddg=<encoded-url>&rut=...``;
    :func:`_unwrap_ddg_url` decodes them. Markup is scraped defensively: any
    structural change simply yields zero results (never fabricated data).

    Internal state attributes are prefixed ``_af_`` because CPython 3.13's
    ``HTMLParser`` grew its own ``_pending`` buffer attribute -- a plain
    ``self._pending`` here collided with stdlib internals (TypeError inside
    ``close()``).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchResult] = []
        self._af_pending: SearchResult | None = None
        self._af_capture: str | None = None
        self._af_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = {k: (v or "") for k, v in attrs}
        classes = attr_map.get("class", "")
        href = attr_map.get("href", "")
        if "result__a" in classes:
            self._flush_pending()
            self._af_pending = SearchResult(title="", url=href, snippet="")
            self._af_capture = "title"
            self._af_buffer = []
        elif "result__snippet" in classes and self._af_pending is not None:
            self._af_capture = "snippet"
            self._af_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._af_capture is None:
            return
        text = " ".join("".join(self._af_buffer).split())
        if self._af_pending is not None:
            if self._af_capture == "title":
                self._af_pending.title = text
            elif self._af_capture == "snippet":
                self._af_pending.snippet = text
        self._af_capture = None
        self._af_buffer = []

    def handle_data(self, data: str) -> None:
        if self._af_capture is not None:
            self._af_buffer.append(data)

    def close(self) -> None:
        super().close()
        self._flush_pending()

    def _flush_pending(self) -> None:
        if self._af_pending is not None and self._af_pending.title:
            self.results.append(self._af_pending)
        self._af_pending = None


_AD_URL_PATTERN = re.compile(r"duckduckgo\.com/y\.js", re.IGNORECASE)


def _unwrap_ddg_url(href: str) -> str | None:
    """Normalize a DDG anchor href into a plain destination URL."""
    href = (href or "").strip()
    if not href or href.lower().startswith("javascript:"):
        return None
    if href.startswith("//"):
        href = "https:" + href
    try:
        parts = urlsplit(href)
    except ValueError:
        return None
    if parts.path in ("/l", "/l/"):
        uddg = parse_qs(parts.query).get("uddg", [None])[0]  # type: ignore[list-item]
        if uddg:
            return unquote(uddg)
        return None
    if _AD_URL_PATTERN.search(href):
        return None
    return href


class DuckDuckGoProvider(WebSearchProvider):
    """Best-effort keyless provider using the DuckDuckGo HTML endpoint.

    Honest limitations (by design, documented):

    * This scrapes a public HTML page; DuckDuckGo can change markup, serve a
      bot-challenge, or rate-limit at any time. Failures surface as
      exceptions/empty result lists -- results are never invented.
    * No result ranking guarantees; only the first page is fetched.
    """

    name = "duckduckgo"

    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._transport = transport
        self._timeout = timeout

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Fetch and parse one page of DDG results for ``query``."""
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        with httpx.Client(
            headers=headers,
            timeout=self._timeout,
            transport=self._transport,
            follow_redirects=True,
        ) as client:
            response = client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query, "kl": "us-en"},
            )
            response.raise_for_status()

        parser = _DDGResultParser()
        parser.feed(response.text)
        parser.close()

        results: list[SearchResult] = []
        for hit in parser.results:
            url = _unwrap_ddg_url(hit.url)
            if not url or not hit.title:
                continue
            results.append(
                SearchResult(title=hit.title, url=url, snippet=hit.snippet)
            )
            if len(results) >= max_results:
                break
        return results


# ---------------------------------------------------------------------------
# Brave Search API (env BRAVE_API_KEY)
# ---------------------------------------------------------------------------

class BraveSearchProvider(WebSearchProvider):
    """Provider for the Brave Search API (https://api.search.brave.com).

    Reads the token from the ``BRAVE_API_KEY`` env var (or the ``api_key``
    constructor argument; tests may pass an explicit key). Never hardcodes a
    real key anywhere in the repo.
    """

    name = "brave"
    _endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(
        self,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("BRAVE_API_KEY", "")
        self._transport = transport
        self._timeout = timeout

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Query the Brave web-search endpoint and parse JSON results."""
        if not self._api_key:
            raise RuntimeError(
                "BraveSearchProvider requires BRAVE_API_KEY (env) or api_key argument"
            )
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self._api_key,
            "User-Agent": _USER_AGENT,
        }
        with httpx.Client(
            headers=headers,
            timeout=self._timeout,
            transport=self._transport,
            follow_redirects=True,
        ) as client:
            response = client.get(
                self._endpoint,
                params={"q": query, "count": max(1, min(max_results, 20))},
            )
            response.raise_for_status()

        payload: Any = response.json()
        web_block = payload.get("web") if isinstance(payload, dict) else None
        raw_items = web_block.get("results", []) if isinstance(web_block, dict) else []
        results: list[SearchResult] = []
        for item in raw_items[: max(0, max_results)]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            snippet = str(item.get("description") or "").strip()
            if not url:
                continue
            results.append(
                SearchResult(title=title, url=url, snippet=snippet)
            )
        return results


# ---------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------

class WebSearchTool(Tool):
    """Tool: search the web and return {title, url, snippet} hits.

    Provider selection: ``BraveSearchProvider`` when ``BRAVE_API_KEY`` is set
    (either env or explicit provider injection), else ``DuckDuckGoProvider``.
    Offline-safe: network/parse failures yield ``ToolResult(ok=False)`` with a
    clear error; results are never fabricated.
    """

    name = "web_search"
    description = (
        "Search the public web for current information relevant to the mission. "
        "Returns a list of results with title, url and snippet. Use for market "
        "research, benchmarks, competitor facts and citations. Requires network "
        "access; fails honestly (ok=False) when offline or blocked."
    )
    parameters_json_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query. Be specific; add the year for freshness.",
                "minLength": 1,
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (1-20).",
                "default": 5,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, provider: WebSearchProvider | None = None) -> None:
        """Create the tool. ``provider`` overrides automatic selection."""
        if provider is not None:
            self._provider = provider
        elif os.environ.get("BRAVE_API_KEY"):
            self._provider: WebSearchProvider = BraveSearchProvider()
        else:
            self._provider = DuckDuckGoProvider()

    @property
    def provider_name(self) -> str:
        """Name of the active provider (reported in results)."""
        return self._provider.name

    def run(self, inputs: dict) -> ToolResult:
        """Execute a search. Inputs: ``query`` (str), ``max_results`` (int, 1-20)."""
        query = inputs.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult(ok=False, error="web_search requires a non-empty 'query' string")
        query = query.strip()

        raw_max = inputs.get("max_results", 5)
        try:
            max_results = int(raw_max)
        except (TypeError, ValueError):
            return ToolResult(ok=False, error=f"max_results must be an integer, got {raw_max!r}")
        max_results = max(1, min(max_results, 20))

        try:
            results = self._provider.search(query, max_results)
        except httpx.HTTPError as exc:
            return ToolResult(
                ok=False,
                error=(
                    f"web search failed (provider={self._provider.name}, network error): "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                error=(
                    f"web search failed (provider={self._provider.name}): "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

        return ToolResult(
            ok=True,
            data={
                "query": query,
                "provider": self._provider.name,
                "count": len(results),
                "results": [r.to_dict() for r in results],
                "note": (
                    "Results come from a best-effort keyless endpoint; verify "
                    "claims against the linked sources."
                    if self._provider.name == "duckduckgo"
                    else None
                ),
            },
        )
