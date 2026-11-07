"""Stdlib HTTP calls to the crawl4AI API: /health, /md and /crawl."""

import http.client
import json
import urllib.error
import urllib.request
from typing import Any


MAX_REASON = 300
# Everything here goes to the VM on loopback, with the token: a configured proxy must not see it.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ApiError(Exception):
    """An HTTP, connection or decoding failure, with a one-line reason."""


def one_line(reason: object) -> str:
    """Collapse a reason to a single bounded line: crawl4AI's 502 detail is a multi-line traceback."""
    text = " ".join(str(reason).split())
    return text if len(text) <= MAX_REASON else f"{text[: MAX_REASON - 3]}..."


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
        with _OPENER.open(req, timeout=timeout) as resp:
            decoded = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = raw
        detail = parsed.get("detail", raw) if isinstance(parsed, dict) else raw
        msg = one_line(f"HTTP {exc.code} from {url}: {detail}")
        raise ApiError(msg) from exc
    except (OSError, http.client.HTTPException) as exc:  # URLError and timeouts are OSError
        msg = one_line(f"{url}: {exc}")
        raise ApiError(msg) from exc
    except ValueError as exc:
        msg = one_line(f"{url}: the response is not JSON: {exc}")
        raise ApiError(msg) from exc
    if not isinstance(decoded, dict):
        msg = f"{url}: the response is not a JSON object"
        raise ApiError(msg)
    return decoded


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
