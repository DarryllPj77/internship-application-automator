"""Explicit search routing; no fallback requests or duplicate Brave charges."""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import requests
from dotenv import dotenv_values

from partner_matcher import BraveSearch, SearchFailure, configured_search_key

PROVIDERS = ("Brave", "SearXNG", "Hybrid")
BOARD = re.compile(r"site:(?:[\w-]+\.)*(?:linkedin\.com|jobstreet\.com|indeed\.com)\b", re.I)


def setting(root, name, default=""):
    return os.environ.get(name) or dotenv_values(Path(root) / ".env").get(name) or default


class SearXNGSearch:
    def __init__(self, url, engines="duckduckgo", *, hybrid=False):
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise SearchFailure("Set SEARXNG_URL to your trusted SearXNG instance URL without credentials or query parameters")
        self.url = url.rstrip("/") + "/search"
        self.engines = engines
        self.hybrid = hybrid

    def search(self, query):
        # Select exactly one engine group. Never silently retry via a paid provider.
        engines = "braveapi" if self.hybrid and BOARD.search(query) else self.engines
        try:
            response = requests.get(self.url, params={"q": query, "format": "json", "engines": engines,
                "language": "en", "pageno": 1}, timeout=(5, 30), allow_redirects=False)
        except requests.RequestException:
            raise SearchFailure("SearXNG is unreachable or timed out; start your instance. No fallback request was made") from None
        if response.status_code != 200:
            hint = " Enable JSON in SearXNG settings.yml." if response.status_code == 403 else ""
            raise SearchFailure(f"SearXNG returned HTTP {response.status_code}.{hint}")
        try:
            payload = response.json()
            results = payload["results"]
            if not isinstance(results, list):
                raise ValueError()
            if not results and payload.get("unresponsive_engines"):
                raise SearchFailure("SearXNG engines failed or were rate limited. Check the instance logs; no fallback was made")
            return [{"title": str(x.get("title", "")), "url": str(x.get("url", "")),
                     "description": str(x.get("content", ""))} for x in results if isinstance(x, dict)][:10]
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            if isinstance(exc, SearchFailure):
                raise
            raise SearchFailure("SearXNG returned invalid JSON search results") from None


def search_client(root, provider, *, brave_key=None):
    if provider == "Brave":
        return BraveSearch(configured_search_key(root) if brave_key is None else brave_key)
    if provider not in PROVIDERS:
        raise SearchFailure("Choose a supported search provider")
    return SearXNGSearch(setting(root, "SEARXNG_URL", "http://127.0.0.1:8080"),
                        setting(root, "SEARXNG_ENGINES", "duckduckgo"), hybrid=provider == "Hybrid")


def provider_picker(root, key, *, disabled=False):
    import streamlit as st
    default = setting(root, "SEARCH_PROVIDER", "Brave")
    provider = st.selectbox("Search provider", PROVIDERS,
        index=PROVIDERS.index(default) if default in PROVIDERS else 0, key=key, disabled=disabled)
    if provider == "Hybrid":
        st.caption("Hybrid: job-board site filters use SearXNG's braveapi engine; other queries use its general engines. Brave requests count toward your allowance. No automatic fallback.")
    elif provider == "SearXNG":
        st.caption("Uses your configured SearXNG general engines. Availability and query syntax depend on those engines.")
    return provider
