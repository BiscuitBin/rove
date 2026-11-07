"""The end-to-end harness: static fixture sites served on 127.0.0.1, without the network.

`serve_site(name)` serves `tests/fixtures/sites/<name>/` over the standard library's
`http.server` on an ephemeral port, in a background thread, and returns the base URL;
given a `Path`, it serves that directory instead, such as a templated copy in tmp_path.
Every server the test started is shut down, closed and joined when the test ends.

A path may be scripted. `script={"/guide/flaky.html": [Answer(503, ...)]}` answers that
path's requests from the list, one answer per request, then serves the file as usual;
`always={"/robots.txt": Answer(500)}` answers every request to the path the same way,
once its script (if any) is used up. `DROP` closes the connection without a response.
Every request is logged, scripted or not: `serve_site.log(base)` gives `(path, arrival)`
in arrival order, the arrival a `time.monotonic()` reading, and `serve_site.paths(base)`
the paths alone.

The scenarios share `tests/fakes.py` with the unit suite, so the tests directory is put on
`sys.path` before any of them is imported.
"""

import functools
import http.server
import sys
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import pytest

TESTS = Path(__file__).resolve().parents[1]
SITES = TESTS / "fixtures" / "sites"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))


@dataclass(frozen=True)
class Answer:
    """A scripted answer: a status, its headers and a body, or a dropped connection."""

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: str = ""
    drop: bool = False


# Close the connection without sending a response: the client sees a transport error.
DROP = Answer(status=0, drop=True)


class _Script:
    """One server's scripted answers and its request log, shared by its handler threads."""

    def __init__(
        self, script: Mapping[str, Sequence[Answer]], always: Mapping[str, Answer]
    ) -> None:
        self._lock = threading.Lock()
        self._script = {path: list(answers) for path, answers in script.items()}
        self._always = dict(always)
        self._log: list[tuple[str, float]] = []

    def answer_for(self, path: str) -> Answer | None:
        """Log the request; the next scripted answer, else the standing one, else None."""
        with self._lock:
            self._log.append((path, time.monotonic()))
            queue = self._script.get(path)
            if queue:
                return queue.pop(0)
            return self._always.get(path)

    def log(self) -> list[tuple[str, float]]:
        """A copy of the request log."""
        with self._lock:
            return list(self._log)


class _Server(http.server.ThreadingHTTPServer):
    """A threading server whose `server_close` joins every request thread it started."""

    daemon_threads = False
    script: _Script


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Serves files from a directory, answers scripted paths, and logs nothing to stderr."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002  The stdlib's parameter name.
        del format, args

    def do_GET(self) -> None:
        """A scripted answer for the path, else the file."""
        server = self.server
        assert isinstance(server, _Server)
        answer = server.script.answer_for(urlsplit(self.path).path)
        if answer is None:
            super().do_GET()
            return
        if answer.drop:
            self.close_connection = True
            return
        body = answer.body.encode()
        self.send_response(answer.status)
        for name, value in answer.headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def _serve(directory: Path, script: _Script) -> Iterator[str]:
    handler = functools.partial(_QuietHandler, directory=str(directory))
    server = _Server(("127.0.0.1", 0), handler)
    server.script = script
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


class SiteServer:
    """The `serve_site` factory: serves a site, and reads back each server's request log."""

    def __init__(self, stack: ExitStack) -> None:
        """Serve within `stack`, which closes every server when the test ends."""
        self._stack = stack
        self._scripts: dict[str, _Script] = {}

    def __call__(
        self,
        site: str | Path,
        *,
        script: Mapping[str, Sequence[Answer]] | None = None,
        always: Mapping[str, Answer] | None = None,
    ) -> str:
        """Serve the fixture site `site` (a name) or the directory `site` (a Path)."""
        directory = site if isinstance(site, Path) else SITES / site
        if not directory.is_dir():
            msg = f"no fixture site {site!r} under {SITES}"
            raise FileNotFoundError(msg)
        scripted = _Script(script or {}, always or {})
        base = self._stack.enter_context(_serve(directory, scripted))
        self._scripts[base] = scripted
        return base

    def log(self, base: str) -> list[tuple[str, float]]:
        """Every request the server at `base` received: its path and monotonic arrival."""
        return self._scripts[base].log()

    def paths(self, base: str) -> list[str]:
        """The paths the server at `base` was asked for, in arrival order."""
        return [path for path, _ in self.log(base)]


@pytest.fixture
def serve_site() -> Iterator[SiteServer]:
    """A factory: `serve_site("basic")` serves that fixture site and returns its base URL.

    A `Path` names a directory to serve as it is; `script`, `always` and the request log
    are described in the module docstring.
    """
    with ExitStack() as stack:
        yield SiteServer(stack)
