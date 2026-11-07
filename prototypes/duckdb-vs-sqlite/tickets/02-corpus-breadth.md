# 02: Corpus breadth

**What to build:** the builder gains the four streamed sources, each selected by the
`--sources` flag and bounded by a per-source cap, and labels every row with its regime so
results can be reported per source as well as overall:

- Sphinx archives (python 3.12, 3.13 and 3.14, numpy 2.2, pandas 2.2.3, django 5.1 and
  the sqlite documentation), about 130 MB of zip downloads and about 9.8k pages.
- Wikipedia article HTML from the Wikimedia Enterprise dump of Simple English Wikipedia,
  namespace 0, run `20250320`. That run is about twenty months old at the time of
  writing, so the content is a sample of article markup, not current Wikipedia. The
  tarball is streamed and reading stops after about 30k articles.
- Common Crawl raw pages from the first WARC file of crawl `CC-MAIN-2026-43`, streamed
  for about 10k HTML responses with full site chrome.
- GitHub issue and comment bodies from GH Archive hourly files for 2026-10-01, about
  20k Markdown bodies. Five hours were planned; the first five held 10.9k bodies, so the
  build reads ten. These rows have a null HTML column.

HTML-only sources get their Markdown from a throwaway converter running in a process
pool. Downloads are cached under `ai_tmp/duckdb-vs-sqlite/downloads/` and, where the
source allows (tar.gz, WARC gz, GH Archive gz), streamed partially and stopped at the
cap. The size table gains a per-regime breakdown: raw bytes against stored bytes, per
store and per regime.

**Blocked by:** 01 (Tracer bullet on local data).

**Status:** done

- [x] A full build reports per-regime counts within the agreed caps: Rust 62k pages or
  the given `--limit`, Sphinx about 9.8k, Wikipedia about 30k, Common Crawl about 10k,
  GitHub about 20k (measured: 62,067, 9,703, 30,000, 9,999 and 19,111)
- [x] A rerun with cached downloads performs no network access
- [x] The size table shows one row per store per regime as well as the overall rows
- [x] `just check` is green
