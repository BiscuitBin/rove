# 04: `fcproto scrape <url>`

**Network:** none beyond the scrape itself, which fetches the public page it is given
through the running stack.

**What to build:** the single-URL fetch the whole prototype exists to demonstrate.
`fcproto scrape https://example.com` asks the running Firecrawl for the page as Markdown
and prints the Markdown to stdout, so it can be piped to a file, with the metadata
(status code, source URL, title) on stderr, so it never pollutes the Markdown. The
command talks to the API's `POST /v2/scrape` over plain HTTP from the standard library,
with no `Authorization` header, and maps a few options onto the request body:

- `--json` prints the raw response body instead of the Markdown, for inspection.
- `--timeout <seconds>` sets the request's `timeout` field (the API takes milliseconds)
  and bounds the client's own wait.
- `--only-main-content` / `--full-page` set `onlyMainContent` in the body; the default
  is the API's default.

Failure is visible and non-zero: a scrape the API rejects or cannot complete exits
non-zero and prints the API's own error text to stderr; running the command when the
machine is absent or stopped exits non-zero with a message that names `fcproto up` as
the fix, rather than a connection-refused traceback.

Record in `FINDINGS.md` the time a scrape takes once the stack is warm, and any page the
stack refuses (the browser service's SSRF guard rejects private addresses by design).

**Blocked by:** 03 (Firecrawl stack up and ready).

**Status:** ready-for-agent

- [ ] `uv run fcproto scrape https://example.com` prints the page's Markdown to stdout
  and nothing else there; the status code, source URL and title go to stderr
- [ ] `uv run fcproto scrape https://example.com > page.md` leaves a file holding only
  the Markdown
- [ ] `--json` prints the raw response body and nothing else on stdout
- [ ] `--timeout` and `--only-main-content` / `--full-page` reach the request body (shown
  by `--json` output or by a logged request)
- [ ] A scrape the API cannot complete (for example a private address the SSRF guard
  refuses, or an unreachable host) exits non-zero and prints the API's error text
- [ ] With no machine, or a stopped one, the command exits non-zero and names
  `fcproto up`, without a traceback
- [ ] `FINDINGS.md` records the warm scrape time and any page the API refused
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
