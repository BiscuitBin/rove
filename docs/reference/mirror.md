---
title: "The mirror on disk"
kind: "reference"
audience: ["user", "contributor", "maintainer", "agent"]
canonical_for: ["mirror_files_reference"]
requires: []
---

# The mirror on disk

A mirror is one output directory. `rovo init` creates it, `rovo sync` fills it and
`rovo index` rebuilds its indexes; the
[command-line reference](cli.md) says when each command writes what. This page
describes every file a mirror holds, as the implementation writes it today. The
specification is `docs/specs/mirror.allium`; decision 0013
([the mirror's state on disk](../decisions/0013-mirror-state-on-disk.md)) fixes the
encoding.

```text
OUT_DIR/
├── rovo.toml              the configuration
├── crawl-report.json      the last sync's report
├── index.md               the index for people: every page and directory index
├── index.jsonl            one IndexEntry per written page
├── links.jsonl            one LinkIndexEntry per URL a page cites
├── llms.txt               the index for agents
├── _indexes/              a directory index per large directory, only when one exists
│   └── 127.0.0.1_8000/
│       └── big.md
├── pages/
│   └── 127.0.0.1_8000/    one directory per host: its host segment
│       └── start.md       one page file per written page, at its assigned path
├── _removed/              the archive, only when a removed page's file is kept
│   └── 127.0.0.1_8000/
│       └── gone.md        a removed page's last published file, at its path
└── .rovo/
    ├── manifest.json      the mirror: scope, profile, pages, aliases, links
    ├── frontier.json      every identity ever discovered, with its status
    ├── sitemaps.json      each sitemap's validators and entries, as last read
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
| `crawl.refollow_unchanged_links` | `true`: a page answered unchanged queues its stored links again | `config.refollow_unchanged_links`, `rovo.allium` |
| `quality.fail_on_low_quality` | `false` | `config.fail_on_low_quality`, `rovo.allium` |
| `mirror.prune` | `false`: a removed page's file is archived under `_removed/`; `true` deletes it | `config.prune`, `mirror.allium` |
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
last saw and stored it, and its fetch times. The validators (`etag` and
`last_modified`) live here alone, never in a page file or an index, so a validator that
moves over an unchanged body rewrites nothing. An alias row is a URL and the identity of
the page it resolves to. A link row is one link of a page as the last finalisation
resolved it: `source` (the linking page's identity), `target_identity` (the
destination's identity, before alias resolution), `fragment` (`null` when there is
none), `kind` (`internal`, `uncrawled`, `dangling` or `external`), `target` (the
identity of the page that holds it, set only when the kind is `internal`) and
`fragment_resolved`. Link rows are sorted by source, then target identity, then
fragment. `rovo init` refuses a directory whose manifest exists, even
one that does not parse; `rovo sync` refuses one that is missing or does not parse.

A page row's `status` is `written` or `removed`. A removed page keeps its record and
its `path`, with `removed_at`, `removal_reason` (`absent`, `redirected_out`,
`out_of_scope` or `merged`) and, for a page redirected out of the scope, the target in
`redirect_target`; it has no alias and no link. A moved page carries `moved_from`, its
old path, until the finalisation that publishes the move. An alias row names a URL that
reached the page: a redirect hop, the URL that answered, or the requested URL a
canonical or a redirect moved past, including a merged page's URL. A URL that is a
written page's own identity is never an alias.

## `.rovo/frontier.json` and `.rovo/runs.json`

`frontier.json` holds `entries`, one row per identity ever discovered (`identity`,
`depth`, `discovered_via`, `discovered_from`, `sitemap_lastmod`, `priority`,
`attempts`, `status`), `observed_urls` and `tier_hints`. `observed_urls` holds one row
per URL a sitemap or `llms.txt` named, in scope or not, sorted by `url`: `url`,
`sources` (the sorted list of `sitemap` and `llms_txt`) and `last_seen_run`, the id of
the last run that saw it; a row unseen for more than `observed_url_retention_syncs` (3)
runs is dropped when the next run's discovery ends. `tier_hints` stays empty until the
browser slice fills it. `sitemaps.json` holds `snapshots`, one row per sitemap ever
read as a sitemap, sorted by `url`: `url`, `etag`, `last_modified`, `is_index`,
`entries` (each `loc` and `lastmod`, in document order) and `last_requested_run`, the
id of the last run that requested the sitemap, whatever it answered. It is written with
`frontier.json`, a dry run's included; a later sync sends a snapshot's validators, and a
`304` answer reuses its entries. A snapshot is dropped when its sitemap answers absent
(`404` or `410`) or with something that is not a sitemap, and, when the next run's
discovery ends, once it has gone unrequested for more than
`observed_url_retention_syncs` (3) runs; an unavailable or unreachable answer keeps it.
An absent file holds no snapshot. `runs.json` holds `runs`, one row per run, oldest
first: `id`, `kind`, `mode`, `status`, `scope_hash`, `dry_run`, `started_at`,
`finished_at` and `unresolved_urls`. A run's id is one more than the highest id there.
Both files are written only after the manifest, so a frontier row marked `done` always
has its page in the manifest; a sync that stops before then saves neither. A dry run
(`rovo sync --dry-run`) saves the manifest, the frontier with the rows its discovery
queued, all still `pending`, and its row in `runs.json`, and writes `crawl-report.json`;
it writes no page file and no index.

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
segment is then rewritten on its own (see below), and each directory is then spelt as
the paths the mirror already holds spell it.

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

A directory has one spelling: compared ignoring case, each directory takes the spelling
a page's path (the page's own included) already uses for it, so with `sub/a.md` held,
`/Sub/b.html` gives `sub/b.md`, and a page at `sub/x.md` whose URL becomes `/Sub/x.html`
keeps its path. Where held paths already spell a directory several ways, the held path
first by code point gives the spelling (`Sub/` before `sub/`); no page already held is
moved. The file name keeps its own spelling and meets the collision rule below.

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
In the body, only a heading with an id in the source ends in that id, after `#` and
inside braces, written as the page records it, and fenced code holds the code text
unchanged, each `<br>` in it a line break. `content_digest` covers the body only. A page file is written only when its text would
change.

## Links

Every sync's finalisation resolves the links of every page in the mirror, not only the
pages it fetched. Each link destination of a page's converted body is made absolute
against the page's source URL and turned into an identity. Destinations in frontmatter,
fenced code and inline code, images, empty destinations and `mailto:`, `tel:`,
`javascript:` and `data:` destinations are never links and stay as written. A
destination is read as CommonMark reads it: balanced parentheses belong to it, so a
destination `x_(y).html` is read whole, and so is link text holding balanced brackets
or an image, whose own source is no link. A link is:

- `internal` when a page in the mirror holds the identity, directly or through an
  alias; its fragment is resolved when the page records that heading anchor;
- `dangling` when the identity is a removed page's;
- `uncrawled` when no page holds it but the scope's bounds, without regard to depth,
  include it, such as a page robots.txt disallows or one past `max_depth`;
- `external` otherwise.

A destination that cannot be parsed as a URL, such as one whose port is out of range,
is out of the scope's bounds: it is never queued, records no link and stays as written.

In the page file an internal destination becomes the relative path from the linking
file to the target file, plus its fragment, and a link from a page to its own heading
becomes the bare fragment (`#intro`). Between hosts the path climbs to `pages/` and
descends again: `pages/127.0.0.1_8001/start.md` links `pages/127.0.0.1_8002/y.md` as
`../127.0.0.1_8002/y.md`. An autolink (`<http://...>`) to a mirrored page becomes an
inline link whose text is the URL. Every other destination stays absolute, and every
other byte of the body is the converted body's. Rewriting always starts from the
converted body, so it gives the same file every time.

The page's link flags follow its links: `uncrawled_internal` when a link is
`uncrawled`, `unresolved_fragment` when an internal link names an anchor the target
does not have, and `dangling_inbound` when a link is `dangling`. By default none of
them makes the page low confidence.

After the page files are written, the pass reads each one back and lists every
relative destination outside code that leads out of the mirror (`outside_mirror`),
reaches no file (`missing_file`) or names an anchor that the target file has no
heading id for and that the page's links do not already flag as unresolved
(`fragment_not_found`); a missing page file is one `missing_file` row with an empty
`href`. After a complete pass the list is empty. It becomes the report's
`broken_links`.

## Indexes

Every finalisation, after the page files are written and read back, builds the indexes
from the written pages and their links and writes them at the mirror's root;
`rovo index` builds them the same way from the manifest alone, re-resolving no link and
reading no page body. They are regenerated from scratch each time and held nowhere
else: the manifest does not record them. Each is a pure function of the manifest's
pages and links and of two `mirror.allium` config values, `hierarchical_index_threshold`
(200) and `llms_txt_cap` (2000), and none carries a time, so a rebuild over an unchanged
mirror gives the same bytes. Every file is UTF-8 with LF line ends and ends in a line
feed. A file is written, atomically, only when its bytes differ; every file under
`_indexes/` the build does not write is deleted, and a directory there left empty is
removed, `_indexes/` itself included (the specification does not say whether an emptied
directory stays; rovo removes it).

Every path an index records is mirror-relative (`pages/<host>/...`), and every link is
relative to the index file: `index.md` and `llms.txt` link down into `pages/` and
`_indexes/`, and `_indexes/<host>/api.md` links its pages as
`../../pages/<host>/api/ref.md`. The exact text of each file below, the encoding of the
two JSON Lines files and `word_count` are those `mirror.allium` states in `BuildIndexes`.

A page line is a Markdown list item: a hyphen, a space, then a link whose text is the page's title
and whose destination is the relative path. In the link text each `\`, `[` and `]` of
the title is escaped with a backslash, and each line break or run of whitespace becomes
one space; a low-confidence page's line goes on with a
space and `(low confidence)`. A directory-index line is the same with `<host>/<dir>` as
the link's text. Blocks of lines are separated by one blank line.

### `index.md`

`# Index`, then for each host in name order `## <host segment>`, the host's top-level
pages (those directly under `pages/<host>/`) in path order, then for each top-level
directory in name order `### <directory>`: the directory indexes at or below it,
shallowest first, then every page below it in path order. Top-level directories that
differ only in case share one heading, in lower case. A mirror with no page writes
`# Index` alone.

### `_indexes/<host>/<dir>.md`

A directory below a host's top level that holds more than `hierarchical_index_threshold`
pages directly (not counting its subdirectories; directories that differ only in case
count as one) gets a directory index at `_indexes/<host>/<dir>.md`, lower-cased:
`pages/<host>/API` and `pages/<host>/api` share `_indexes/<host>/api.md`. A host's top
level never gets one. The file is `# <host>/<dir>`, then a line for each nearest indexed
descendant (the directory indexes below its own with no other directory index between,
so `api.md` links `api/v2/ref.md` when `api/v2` has no index), then a line for each of
its own pages in path order.

### `llms.txt`

`# <host segment>` of the first page by path (`# Index` for an empty mirror), then
`> <summary>` unless the summary is empty, then one page line per page in path order,
linked from the mirror's root. The summary is the description of the page whose
identity, or one of whose aliases, is a start URL's identity (the first such start URL
in the configured order), else of the page the root URL names the same way, else of the
first page by path; it is written as it is, unescaped. When the written pages number more than `llms_txt_cap`, a directory with its own
directory index is listed as one directory-index line in place of its pages; a host's
top-level pages and the pages of a directory without an index are still listed.

### `index.jsonl` and `links.jsonl`

One JSON object per line, keys sorted, compact separators (`,` and `:`), non-ASCII
characters written as themselves, a set as a sorted list, an enum value (a link's
`kind`, each quality flag) as its name, an absent value as `null`,
and a line feed after every line, so an empty mirror writes an empty file.

`index.jsonl` holds one `IndexEntry` per written page, sorted by `path`: `path`,
`identity`, `source_url`, `title`, `description`, `keywords`, `headings`,
`quality_score`, `low_confidence`, `quality_flags`, `content_digest`, `version`,
`locale`, `word_count` (the number of words the quality measurement counted
outside code), and `outbound_internal` and `inbound_internal`, the page's counts of
internal links out and in.

`links.jsonl` holds one `LinkIndexEntry` per identity a written page links to, without
its fragment, sorted by `url`: `url`, `kind` (as [Links](#links) defines it), `path`
(the holding page's path when the kind is `internal`, else `null`) and `cited_by`, the
sorted paths of the pages that link to it.

## `_removed/`

The archive mirrors `pages/`: a removed page's file at `pages/<host>/<path>` is kept at
`_removed/<host>/<path>`, the path the page's record keeps. A page answered again is
written again at that path when it is still free (else at the path its identity is
assigned), and its archived copy is deleted; a page that moves onto a removed page's
identity replaces that record, and its archived copy is deleted too. With
`mirror.prune = true` in `rovo.toml`, a removed page's file is deleted instead of
archived. A page answered again and removed again in the same sync keeps its archived
copy, even when it was answered at a new path: that path was never published, so
nothing is archived from it.

No file moves while a sync fetches. A removal, a move or a revival is recorded in
memory, and the finalisation applies the file changes in order before it publishes the
pages: a file is archived, an archived copy deleted, then, once the new file is
written, a moved page's old file deleted unless another page now holds that path. Each
change is idempotent, so a sync interrupted before its finalisation leaves the files as
the last finished sync left them. A sync that stops inside the finalisation, after a
file change and before the manifest is saved, can leave the files ahead of the
manifest: the next finalisation writes any written page whose file is missing. A
directory under `pages/` or `_removed/` left empty is removed, `pages/` and `_removed/`
included (the specification does not say whether an emptied directory stays; rovo
removes it, as it does under `_indexes/`).

## `crawl-report.json`

The report of the last sync: every `CrawlReport` field of `rovo.allium` but the mirror,
the operator and the open or written status. It names the run (`run_id`, `kind`,
`mode`), how it ended (`report_status`, `exit_code`, `error`), the configuration and
options it used, the tallies (`discovered`, the frontier's rows when discovery ended, `fetched`, `converted`, `bytes_fetched`
and the rest), one row per host, the quality summary and scores, the low-confidence
pages, the broken links (`from_path`, `href`, `reason`, sorted by `from_path` then
`href`) and one row per change (`kind`, `url`, `path`, `moved_from`): `added`,
`changed`, `unchanged`, `moved` (with the old path in `moved_from`), `removed` (once per
removal, with the path the record keeps) or `failed`. Every list is
sorted by URL or path, durations are seconds, and `started_at` and `finished_at` are
the only times. `rovo sync` writes it once, when the report is ranked; a refused sync
writes none yet.

## Related pages

- [Command-line reference](cli.md)
- [Decision 0013: the mirror's state on disk](../decisions/0013-mirror-state-on-disk.md)
