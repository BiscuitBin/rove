"""Stdlib HTTP calls to the crawl4AI API: /health, /md and /crawl."""

import json
import urllib.error
import urllib.request
from typing import Any


class ApiError(Exception):
    """An HTTP or connection failure, with a one-line reason."""


def _request(
    url: str, token: str | None = None, body: dict[str, Any] | None = None, timeout: float = 120
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  http to localhost
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            detail = json.loads(raw).get("detail", raw)
        except ValueError:
            detail = raw
        msg = f"HTTP {exc.code} from {url}: {detail}"
        raise ApiError(msg) from exc
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
        msg = f"{url}: {exc}"
        raise ApiError(msg) from exc


def health(base: str) -> dict[str, Any]:
    """GET /health: no token needed."""
    return _request(f"{base}/health", timeout=5)


def markdown(base: str, token: str, url: str, filt: str = "raw") -> dict[str, Any]:
    """POST /md: one page's Markdown through the chosen filter."""
    return _request(f"{base}/md", token, {"url": url, "f": filt, "c": "0"})


def crawl(base: str, token: str, url: str) -> dict[str, Any]:
    """POST /crawl: the full result for one URL, cache bypassed."""
    body = {
        "urls": [url],
        "browser_config": {"type": "BrowserConfig", "params": {"headless": True}},
        "crawler_config": {"type": "CrawlerRunConfig", "params": {"cache_mode": "bypass"}},
    }
    return _request(f"{base}/crawl", token, body)
