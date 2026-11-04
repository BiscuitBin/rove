"""The end-to-end harness: static fixture sites served on 127.0.0.1, without the network.

`serve_site(name)` serves `tests/fixtures/sites/<name>/` over the standard library's
`http.server` on an ephemeral port, in a background thread, and returns the base URL;
given a `Path`, it serves that directory instead, such as a templated copy in tmp_path.
Every server the test started is shut down, closed and joined when the test ends.
"""

import functools
import http.server
import threading
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

import pytest

SITES = Path(__file__).resolve().parents[1] / "fixtures" / "sites"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Serves files from a directory and logs nothing to stderr."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002  The stdlib's parameter name.
        del format, args


class _Server(http.server.ThreadingHTTPServer):
    """A threading server whose `server_close` joins every request thread it started."""

    daemon_threads = False


@contextmanager
def _serve(directory: Path) -> Iterator[str]:
    handler = functools.partial(_QuietHandler, directory=str(directory))
    server = _Server(("127.0.0.1", 0), handler)
    # A short poll, so that shutdown() returns promptly rather than after the default 0.5 s.
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, name="e2e-site", daemon=True
    )
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host!s}:{port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def serve_site() -> Iterator[Callable[[str | Path], str]]:
    """A factory: `serve_site("basic")` serves that fixture site and returns its base URL.

    A `Path` names a directory to serve as it is.
    """
    with ExitStack() as stack:

        def serve(site: str | Path) -> str:
            directory = site if isinstance(site, Path) else SITES / site
            if not directory.is_dir():
                msg = f"no fixture site {site!r} under {SITES}"
                raise FileNotFoundError(msg)
            return stack.enter_context(_serve(directory))

        yield serve
