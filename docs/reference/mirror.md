---
title: "The mirror on disk"
kind: "reference"
audience: ["user", "contributor", "maintainer", "agent"]
canonical_for: ["mirror_files_reference"]
requires: []
---

# The mirror on disk

A mirror is one output directory. `rovo init` creates it and `rovo sync` fills it; the
[command-line reference](cli.md) says when each command writes what. This page
describes every file a mirror holds, as the implementation writes it today. The
specification is `docs/specs/mirror.allium`; decision 0013
([the mirror's state on disk](../decisions/0013-mirror-state-on-disk.md)) fixes the
encoding.

```text
OUT_DIR/
├── rovo.toml              the configuration
├── crawl-report.json      the last sync's report
├── pages/
│   └── 127.0.0.1_8000/    one directory per host: its host segment
│       └── start.md       one page file per written page, at its assigned path
└── .rovo/
    ├── manifest.json      the mirror: scope, profile, pages, aliases, links
    ├── frontier.json      every identity ever discovered, with its status
    └── runs.json          one row per run
```

Every JSON file is UTF-8, its keys sorted, indented two spaces and ending in one line
feed. It is written to a temporary file in the same directory, flushed, synced and
moved into place, so an interrupted write leaves the previous file whole. Timestamps
are ISO 8601 in UTC and appear only under `.rovo/` and in the report, never in a page
file. Sets are written as sorted lists.

## `rovo.toml`

`rovo init` writes every key with its value; a key left out takes the built-in default
in the last column. The standard library reads the file with `tomllib`.

| Key | Default | Source of the default |
| --- | --- | --- |
| `site.root_url` | the URL's origin and first path segment (and a locale segment the profile lists) | `initial_scope`, `rovo.allium` |
| `site.start_urls` | `[SITE_URL]` | `initial_scope` |
| `scope.allowed_hosts` | the URL's host, lower-cased, port dropped | `initial_scope` |
| `scope.path_prefixes` | the URL's directory | `initial_scope` |
| `scope.include`, `scope.exclude` | `[]`: no filter; a glob, or a regular expression after `re:` | `CrawlScope`, `mirror.allium` |
| `scope.max_depth` | `10` | `config.max_depth`, `rovo.allium` |
| `scope.locale` | absent: no locale pinned | `CrawlScope.locale` |
| `scope.meaningful_query_params` | `[]`: the profile's apply | `scope_of` |
| `conversion.profile` | the profile the URL's host picks, else `generic` | `profile_for` |
| `crawl.robots` | `"respect"` | `StandardRunsStayPolite`, `crawl.allium` |
| `crawl.render_mode` | `"never"` | `config.render_mode`, `rovo.allium` |
| `crawl.stealth_mode` | `"off"` | `StealthIsOwnerOnly`, `crawl.allium` |
| `crawl.max_age` | absent: a page never goes stale; a number of seconds | `PrepareRun`, `crawl.allium` |
| `quality.fail_on_low_quality` | `false` | `config.fail_on_low_quality`, `rovo.allium` |
| `unblocking.provider` | absent; any value is a configuration problem | `Configuration`, `rovo.allium` |

An unknown section or key, a value of the wrong type or outside its choices, a profile
the catalogue lacks, or a file that does not parse makes the configuration invalid, and
`rovo sync` names every bad key path on standard error. The configuration's `hash`, in
the report, is the first 16 hex digits of the SHA-256 of the resolved values as
canonical JSON.

## `.rovo/manifest.json`

The mirror: `scope` (the `CrawlScope` the last run used), `profile` (a catalogue
profile's name), `processing_signature` (a digest of the profile and the pinned
locale), `declared_owned_hosts`, `recorded_root_url` (the root URL the last run used),
`pages`, `aliases` and `links`. Each page row holds every `Page` field: its identity,
path, source and canonical URLs, title, description, extraction method, tier, quality
result, flags, keywords, digests, validators, both bodies, frontmatter, the runs that
last saw and stored it, and its fetch times. An alias row is a URL and the identity of
the page it resolves to. `rovo init` refuses a directory whose manifest exists, even
one that does not parse; `rovo sync` refuses one that is missing or does not parse.

## `.rovo/frontier.json` and `.rovo/runs.json`

`frontier.json` holds `entries`, one row per identity ever discovered (`identity`,
`depth`, `discovered_via`, `discovered_from`, `sitemap_lastmod`, `priority`,
`attempts`, `status`), and the lists `observed_urls` and `tier_hints`, empty until the
discovery and browser slices fill them. `runs.json` holds `runs`, one row per run, oldest
first: `id`, `kind`, `mode`, `status`, `scope_hash`, `dry_run`, `started_at`,
`finished_at` and `unresolved_urls`. A run's id is one more than the highest id there.
Both files are written only after the manifest, so a frontier row marked `done` always
has its page in the manifest; a sync that stops before then saves neither.

## Page files

Every page file lies under `pages/`, in its host's directory. The host segment is the
host lower-cased, a trailing `.` dropped, each character outside `[a-z0-9.-]` replaced
with `-`, the device-name rule below applied, then a port other than the scheme's
default appended as `_<port>`: `Docs.Example.` gives `docs.example`, `127.0.0.1:8000`
gives `127.0.0.1_8000`, `con:8080` gives `con-_8080`. Two hosts that sanitise alike
share a directory, and the collision rule below keeps their pages apart. Nothing else
sits under `pages/`, so no page can take the name of a file at the mirror's root.

Below the host segment, a page's path follows its identity: the scope's path prefix is
stripped, a directory URL is named `index` (so the scope root is
`pages/<host>/index.md`), `.html`, `.htm` and `.aspx` are dropped in any case, a last
segment that drop leaves empty is named `index` as for a directory URL (`/guide/.html`
gives `guide/index.md` and `/.html` gives `index.md` under the prefix `/`), each
segment keeps `[A-Za-z0-9._-]` and replaces anything else with `-`, and empty segments
are dropped. The path is never percent-decoded, so each `%` becomes `-` too:
`/guide/%2e%2e/x.html` becomes `-2e-2e/x.md`, never a path outside the mirror. Each
segment is then rewritten on its own:

- a leading `.` and a trailing run of `.` become `-`, so no page is hidden
  (`.git/config.html` gives `-git/config.md`, `page.` gives `page-.md`);
- a directory named, in any case, like a file at the mirror's root (`llms.txt`,
  `index.jsonl`, `links.jsonl`, `crawl-report.json`, `rovo.toml`) or ending in `.md` has
  its last `.` replaced with `-` (`llms.txt/guide.html` gives `llms-txt/guide.md`,
  `a.md/x.html` gives `a-md/x.md`), since a page file is never also a directory;
- a segment whose part before its first `.` is a Windows device name (`CON`, `PRN`,
  `AUX`, `NUL`, `COM1` to `COM9`, `LPT1` to `LPT9`, in any case) gains `-` after that
  part (`con.html` gives `con-.md`, `con.txt` gives `con-.txt.md`).

The rewrites each read the segment as it was before any of them, so their order does not
matter: `con.` gives `con--.md` (the device `-`, then the trailing `.` as `-`).

Last, `.md` is added unless the name already ends in `.md` exactly, in lower case:
`README.md` stays, `README.MD` gives `README.MD.md`. `index.md` and `_index.md` inside a
host's directory are ordinary page names.

A path another page holds, compared ignoring case, or a path over 200 characters
(counted from `pages/`, the host segment included) gets `-` and the first six hex digits
of the identity's SHA-256 instead, the whole path before them cut to 190 characters.
When that suffixed path is unusable too, the suffix is the full 64-hex digest, the path
before it cut so the whole still fits 200 characters. A cut never shortens
`pages/<host>/`, so a host too long to leave room for a page has none. When no path is
usable, the page gets no path: the mirror refuses it, nothing in the mirror changes, its
frontier row is `failed`, and the report lists its URL under `failed_urls` with the
error `no free path` and a `failed` change, so the sync exits 1 (`partial`). The
200-character limit is the mirror's own parameter, not a `rovo.toml` key, and neither is
the layout `pages/{host}/{path}`. A profile that maps a version label into the path is
not yet supported: the sync stops with exit 1.

A page file is `---`, the frontmatter, `---`, then the Markdown body. The frontmatter's
keys are sorted and an absent value is left out. Strings and lists are JSON-quoted
(YAML reads them as double-quoted scalars and flow sequences), booleans are `true` or
`false`, and `quality_score` keeps at most four decimal places:

```yaml
---
content_digest: "8c90353f671f675a46e7d5cc41bb2f97c6cb10b81c79cc679794f485025d869e"
description: "How to start with the example product."
keywords: ["product", "getting", "started", "example", "mirrors", "documentation", "websites", "markdown"]
last_modified: "Sun, 01 Nov 2026 04:24:19 GMT"
locale: "en"
low_confidence: false
method: "profile"
profile: "generic"
quality_flags: []
quality_score: 1.0
source_url: "http://127.0.0.1:8000/guide/start.html"
tier: "http"
title: "Getting started"
---
# Getting started
```

That is the start of `pages/127.0.0.1_8000/start.md` after `rovo sync` of the `one-page` fixture site.
`last_modified` and `etag` are the site's own validators, not a time rovo recorded.
In the body, only a heading with an id in the source ends in that id, after `#` and
inside braces, written as the page records it, and fenced code holds the code text
unchanged, each `<br>` in it a line break. `content_digest` covers the body only. A page file is written only when its text would
change.

## `crawl-report.json`

The report of the last sync: every `CrawlReport` field of `rovo.allium` but the mirror,
the operator and the open or written status. It names the run (`run_id`, `kind`,
`mode`), how it ended (`report_status`, `exit_code`, `error`), the configuration and
options it used, the tallies (`discovered`, `fetched`, `converted`, `bytes_fetched`
and the rest), one row per host, the quality summary and scores, the low-confidence
pages and one row per change (`kind`, `url`, `path`, `moved_from`). Every list is
sorted by URL or path, durations are seconds, and `started_at` and `finished_at` are
the only times. `rovo sync` writes it once, when the report is ranked; a refused sync
writes none yet.

## Related pages

- [Command-line reference](cli.md)
- [Decision 0013: the mirror's state on disk](../decisions/0013-mirror-state-on-disk.md)
