"""The browser tier's engine seam (crawl.allium AttemptTier at the browser tier).

A `BrowserEngine` renders one page and makes no request of its own: every request the
page causes, the navigation and every subrequest, is handed to the crawl's `Answer`
callback, `answer(url, navigation=...)`, which returns the response to fulfil it with,
or None to abort it unrequested (rovo._crawl.run makes each request, under robots.txt
and the host's limiter). `render` returns the rendered DOM once the page reached its
load state, or None when the navigation got no response or the load state was not
reached within `CONFIG.render_max_wait`.

`PlaywrightEngine` is the one real engine: headless Chromium through playwright, which
this module alone imports, and only when the engine first renders, so `import rovo` and
every command that renders nothing never load it.
"""

import importlib
from collections.abc import Callable
from typing import Any, Protocol

from rovo._crawl.model import CONFIG, SiteResponse

# The status a browser follows to the URL an answer's content came from.
_FOUND = 302


class Answer(Protocol):
    """The crawl's request callback a render is answered through."""

    def __call__(self, url: str, *, navigation: bool) -> SiteResponse | None:
        """The answer to fulfil the request with, or None to abort it unrequested."""
        ...


class BrowserEngine(Protocol):
    """An engine that renders a page through the crawl's request callback."""

    def render(self, url: str, answer: Answer) -> str | None:
        """The rendered DOM of `url`, every request answered by `answer`; None on failure."""
        ...

    def close(self) -> None:
        """Release the engine."""
        ...


# What `rovo._commands.sync` and `fetch` take: opens one engine when a run needs it.
EngineFactory = Callable[[], BrowserEngine]


class PlaywrightEngine:
    """The one real BrowserEngine: headless Chromium through playwright.

    Playwright starts and Chromium launches at the first render, once per engine; each
    render opens a page in the engine's one context, whose every request is routed: it
    is fulfilled from the crawl's answer, or aborted, and never let through to the
    network. An answer whose content came from another URL (a redirect the crawl
    followed) is fulfilled as a redirect to that URL, and the browser's request for it
    is fulfilled with the answer itself, so the page stands at the URL its content came
    from. The load state is `load` (T19's batched question, item 3), waited for at most
    `CONFIG.render_max_wait`. A launch that fails (no Chromium) fails every render.
    """

    def __init__(self) -> None:
        """An engine not yet started: nothing is imported or launched until a render."""
        self._api: Any = None
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None

    def render(self, url: str, answer: Answer) -> str | None:
        """The rendered DOM of `url`, every request answered by `answer`; None on failure."""
        api = self._api = self._api or importlib.import_module("playwright.sync_api")
        failures = (api.Error, api.TimeoutError)
        try:
            page = self._started().new_page()
        except failures:
            return None
        held: dict[str, SiteResponse] = {}

        def route(routed: Any) -> None:  # noqa: ANN401  A playwright Route, typed by playwright.
            requested = routed.request.url
            served = held.pop(requested, None) or answer(
                requested, navigation=routed.request.is_navigation_request()
            )
            if served is None or served.status == 0:
                routed.abort()
            elif served.source_url != requested:
                held[served.source_url] = served
                routed.fulfill(status=_FOUND, headers={"location": served.source_url})
            else:
                routed.fulfill(
                    status=served.status, body=served.markup, content_type=served.content_type
                )

        try:
            page.route("**/*", route)
            wait = CONFIG.render_max_wait.total_seconds() * 1000
            response = page.goto(url, wait_until="load", timeout=wait)
            dom: str | None = None if response is None else page.content()
        except failures:
            dom = None
        finally:
            page.close()
        return dom

    def close(self) -> None:
        """Close the browser and stop playwright, when they were started."""
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def _started(self) -> Any:  # noqa: ANN401  A playwright BrowserContext.
        """The engine's one browser context, playwright started and Chromium launched once."""
        if self._playwright is None:
            self._playwright = self._api.sync_playwright().start()
        if self._browser is None:
            self._browser = self._playwright.chromium.launch(headless=True)
        if self._context is None:
            self._context = self._browser.new_context(service_workers="block")
        return self._context
