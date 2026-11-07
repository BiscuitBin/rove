# 04: Full run and write-up

**What to build:** the three scripts run at full scale, in the order build corpus, load
stores, bench queries, and the results page `RESULTS.md` beside them records what they
printed: the size tables overall and per regime, the query table, a verdict on the
question (does DuckDB's column compression make it a better temporary store than SQLite
for raw HTML and Markdown, on disk and in memory while querying), the caveats, and a
recommendation shaped so a later decision record can cite it.

The caveats to state: DuckDB compresses per row group of 122,880 rows, so the ratio on
a small corpus is not the ratio at scale; compression lands at `CHECKPOINT`, not at
insert; every measurement is on a warm cache; Wikipedia and rustdoc markup differ from
fetched pages with site chrome and compress differently; the zstd level used; the
DuckDB memory limit in force for each row.

The README links to the results page.

**Blocked by:** 02 (Corpus breadth), 03 (Query memory and throughput).

**Status:** done, except the commit, which waits for the maintainer

- [x] `RESULTS.md` passes markdownlint, typos and lychee
- [x] Every number on the page is reproducible from the three commands the page quotes
- [x] `just check` is green
- [ ] The branch is committed as the primary source for the prototype, when the maintainer
  asks for the commit
