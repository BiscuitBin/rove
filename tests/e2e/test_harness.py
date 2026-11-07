"""The end-to-end harness itself: a fixture site is served, and the browser marker skips.

The scripted answers, the dropped connection and the request log are proved here before
any scenario relies on them (T12).
"""

import http.client
import urllib.error
import urllib.request
from collections.abc import Callable
from http import HTTPStatus

import pytest
from conftest import DROP, Answer, SiteServer

SERVICE_UNAVAILABLE = 503
SERVER_ERROR = 500
TIMEOUT = 5


def get(url: str) -> tuple[int, dict[str, str], str]:
    """One GET: the status, the headers (lower-cased names) and the body, error or not."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:  # noqa: S310  A local http URL the fixture built.
            return (
                response.status,
                {name.lower(): value for name, value in response.headers.items()},
                response.read().decode("utf-8"),
            )
    except urllib.error.HTTPError as error:
        with error:
            return (
                error.code,
                {name.lower(): value for name, value in error.headers.items()},
                error.read().decode("utf-8"),
            )


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


def test_a_scripted_status_carries_its_headers_and_body(serve_site: SiteServer) -> None:
    """A scripted path answers its status, its headers and its body."""
    base = serve_site(
        "basic",
        script={"/index.html": [Answer(SERVICE_UNAVAILABLE, {"Retry-After": "4"}, "busy")]},
    )
    status, headers, body = get(f"{base}index.html")
    assert status == SERVICE_UNAVAILABLE
    assert headers["retry-after"] == "4"
    assert body == "busy"


def test_a_script_is_used_up_then_the_file_is_served(serve_site: SiteServer) -> None:
    """Each request takes the next scripted answer; then the file is served as usual."""
    first = Answer(SERVICE_UNAVAILABLE)
    second = Answer(SERVER_ERROR)
    base = serve_site("basic", script={"/index.html": [first, second]})
    statuses = [get(f"{base}index.html")[0] for _ in range(3)]
    assert statuses == [SERVICE_UNAVAILABLE, SERVER_ERROR, HTTPStatus.OK]
    assert "<h1>Basic fixture site</h1>" in get(f"{base}index.html")[2]


def test_a_standing_answer_holds_every_time(serve_site: SiteServer) -> None:
    """An `always` answer answers every request to the path, after its script."""
    base = serve_site(
        "basic",
        script={"/index.html": [Answer(SERVICE_UNAVAILABLE)]},
        always={"/index.html": Answer(SERVER_ERROR)},
    )
    statuses = [get(f"{base}index.html")[0] for _ in range(4)]
    assert statuses == [SERVICE_UNAVAILABLE, SERVER_ERROR, SERVER_ERROR, SERVER_ERROR]


def test_a_dropped_connection_sends_no_response(serve_site: SiteServer) -> None:
    """DROP closes the connection without a status line: the client sees a transport error."""
    base = serve_site("basic", always={"/robots.txt": DROP})
    with pytest.raises((http.client.RemoteDisconnected, urllib.error.URLError, ConnectionError)):
        get(f"{base}robots.txt")
    assert get(f"{base}index.html")[0] == HTTPStatus.OK


def test_the_request_log_keeps_arrival_order(serve_site: SiteServer) -> None:
    """Every request is logged with its path and a non-decreasing arrival time."""
    base = serve_site("basic", always={"/robots.txt": Answer(SERVER_ERROR)})
    other = serve_site("basic")
    for path in ("robots.txt", "index.html", "missing.html", "robots.txt"):
        get(f"{base}{path}")
    get(f"{other}index.html")
    assert serve_site.paths(base) == ["/robots.txt", "/index.html", "/missing.html", "/robots.txt"]
    arrivals = [arrival for _, arrival in serve_site.log(base)]
    assert arrivals == sorted(arrivals)
    assert serve_site.paths(other) == ["/index.html"]
