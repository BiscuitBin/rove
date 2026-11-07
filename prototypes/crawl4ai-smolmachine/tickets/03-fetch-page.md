# 03: Fetch one page's Markdown through the microVM

**What to build:** a `fetch <url>` command that asks the crawl4AI API inside the running
microVM for the page and prints its Markdown to stdout. `--filter raw|fit` chooses the
Markdown filter (raw by default). `--json` prints the full crawl result instead, as
returned by the crawl endpoint with the cache bypassed. `-o FILE` writes the output to
a file instead of stdout. The command exits 0 when a page was printed, and exits 1
with a one-line reason, before making any request, when the VM is not up, and when the
fetch fails.

**Blocked by:** 02 (the state file with the token, and a machine that stays up between
invocations).

**Status:** done

- [x] A real public page prints readable Markdown.
- [x] `--json` shows the raw Markdown and the HTTP status code of the fetched page
      inside the first result.
- [x] `-o` writes the file and prints nothing else to stdout.
- [x] `vm down` then `fetch` exits 1 with a clear message.
- [x] A sample run is captured in the README.
