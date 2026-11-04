# Changelog

All notable changes to `rovo` are recorded here. The format follows Keep a Changelog
(<https://keepachangelog.com/en/1.1.0/>). Nothing has been released, so there is no
version section yet; the release ticket adds the first one and states the versioning
policy.

## [Unreleased]

### Added

- The placeholder API, `rovo.__version__`, read from the installed metadata.
- The placeholder command, `rovo --version` and `rovo version`.
- `renovate.json`: Renovate proposes updates to every pin but the two Python versions
  decision 0001 owns, each held for approval on its dependency dashboard, security fixes
  aside (decision 0008).
- The Allium gate: a placeholder root module `docs/specs/rovo.allium` that declares no
  behaviour, the `check-specs` and `analyse-specs` gates over it, the `spec-change` skill
  and the seven Allium skills with their reference material (decisions 0009 to 0011).
- The product specification: four Allium modules under `docs/specs/` (`rovo`, `crawl`,
  `mirror`, `convert`) that specify rovo as a documentation mirror, elicited from the
  product brief with two prototype specifications as evidence, with the product's terms
  in the terminology page (decision 0012). Nothing of it is implemented yet.
- The product's foundation, with no specification behaviour yet: the runtime
  dependencies httpx, beautifulsoup4, lxml and markdownify and the `browser` extra
  (playwright); the private modules `_convert`, `_mirror`, `_crawl`, `_config` and
  `_report` with a test holding their import direction; the end-to-end harness serving
  fixture sites on `127.0.0.1`, the `browser` marker and `just e2e-browser`; and decision
  0013, the mirror's state as JSON under `.rovo/`, written atomically.
- The first slice of the specification: `rovo init SITE_URL OUT_DIR [--profile NAME]`
  writes `rovo.toml` and an empty manifest, and `rovo sync OUT_DIR` reads each allowed
  host's robots.txt, fetches the seed pages it allows over HTTP, converts each to
  Markdown with the generic profile, publishes it as a page file with sorted frontmatter
  and writes `crawl-report.json`. Branches later slices implement stop the sync with
  exit 1; the mirror's files are described in `docs/reference/mirror.md`.
  When a page's path and its short-digest fallback are both held, the page takes the
  full-digest path; when that is held too, the page is refused and reported as a failed
  URL (`no free path`), and the sync exits 1. A page path is never percent-decoded.
  Page files live under `pages/<host>/`, the host segment sanitised (lower case, trailing
  dot dropped, `[a-z0-9.-]`, device names suffixed `-`, a non-default port as
  `_<port>`); hidden, device-named and root-file-named segments are rewritten, `.md` is
  not doubled only for an exact lower-case `.md`, and the 200-character limit counts the
  whole path. A host's trailing dot no longer makes a separate identity. A last URL
  segment that is only a dropped `.html`, `.htm` or `.aspx` (`/guide/.html`) is named
  `index`, as a directory URL is, where `rovo sync` used to crash.
- `rovo sync` follows links: each stored page's content and navigation links that the
  crawl scope allows one level deeper (`max_depth`, `include`, `exclude`, the path
  prefixes, the allowed hosts) are queued and fetched in later batches, each URL once.
  Every finalisation resolves every page's links against the whole mirror: a link to a
  mirrored page is written as a relative path between page files (a link between hosts
  climbs to `pages/`), every other link stays absolute, code is never rewritten, the
  `uncrawled_internal`, `unresolved_fragment` and `dangling_inbound` flags follow the
  links, the manifest keeps the links, and `crawl-report.json` lists any broken
  relative link under `broken_links`. A link to a URL that cannot be parsed (a port out
  of range) is out of bounds: it is never queued, records no link and stays as written,
  where `rovo sync` used to crash. A destination with balanced parentheses
  (`x_(y).html`) is read whole, where it was cut at its first `)`, left absolute and
  recorded as an uncrawled link. Link text is read the same way: text holding
  brackets (`see [1]`) or an image no longer hides the link, or swaps in the image.
- The mirror's indexes: every `rovo sync` finalisation writes `index.md` (a heading per
  host and per top-level directory, linking every page and every directory index),
  `_indexes/<host>/<dir>.md` for a directory holding more than 200 pages directly,
  `index.jsonl` (one entry per page), `links.jsonl` (one entry per cited URL) and
  `llms.txt`, all deterministic, UTF-8 with LF line ends, linked relative to each file
  and rewritten only when their text changes; stale directory indexes are deleted. The
  new command `rovo index OUT_DIR` rebuilds them offline from the manifest, and exits 2
  without a mirror or when a page file is missing or not UTF-8.
