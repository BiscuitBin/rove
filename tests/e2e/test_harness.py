"""The end-to-end harness itself: a fixture site is served, and the browser marker skips."""

import urllib.request
from collections.abc import Callable
from http import HTTPStatus

import pytest


def test_basic_site_is_served(serve_site: Callable[[str], str]) -> None:
    """The basic fixture site answers 200 on 127.0.0.1 with its page's heading."""
    base_url = serve_site("basic")
    assert base_url.startswith("http://127.0.0.1:")
    with urllib.request.urlopen(base_url, timeout=5) as response:  # noqa: S310  A local http URL the fixture built.
        status = response.status
        body = response.read().decode("utf-8")
    assert status == HTTPStatus.OK
    assert "<h1>Basic fixture site</h1>" in body


@pytest.mark.browser
def test_browser_tier_is_importable() -> None:
    """With the browser extra installed, playwright's sync API is there; without it, a skip."""
    sync_api = pytest.importorskip("playwright.sync_api")
    assert callable(sync_api.sync_playwright)
