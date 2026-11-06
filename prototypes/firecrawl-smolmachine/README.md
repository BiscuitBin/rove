# Firecrawl in a smol machine: a throwaway prototype

This directory is a prototype, not product. It exists to answer one question:

> Can the `smolmachines` Python SDK boot and manage a local microVM on macOS that runs
> self-hosted Firecrawl, well enough to fetch single URLs as Markdown through a small
> Typer command?

rovo's specification treats page fetching as a black box (`fetch_or_render` in
`docs/specs/crawl.allium`, `fetch_one` in `docs/specs/rovo.allium`). The prototype is
evidence for a later decision record about the browser fetch tier. It adds nothing under
`src/rovo/`, changes no specification, and is excluded from the repository gates once it
holds Python (ticket 01 adds the excludes). The code is deliberately disposable: the
command is called `fcproto`, there are no tests and no polish, and nothing here is
imported by anything else.

The prototype lives on the `firecrawl-smolmachine-prototype` branch, in its own uv
project (own `pyproject.toml` and `uv.lock`) so that its dependencies never touch the
root lockfile.

## Tickets

The tickets under `tickets/` are numbered in dependency order and written in the
lightweight per-ticket form: what to build, what blocks it, an acceptance checklist.
Each ticket that reaches the network says so at the top; a future agent asks before
pulling anything.

| Ticket | Title | Blocked by |
| --- | --- | --- |
| `01-scaffold-doctor-first-boot.md` | Scaffold, `doctor`, and the first boot | none |
| `02-topology-spike.md` | Topology spike: how the five services will run | 01 |
| `03-firecrawl-stack-up-and-ready.md` | Firecrawl stack up and ready | 02 |
| `04-scrape-command.md` | `fcproto scrape <url>` | 03 |
| `05-stop-and-restart.md` | Stop and restart without rebuilding | 03 |
| `06-verdict.md` | Verdict: `FINDINGS.md` answers the question | 04, 05 |

Ticket 01 settles the riskiest unknown (whether a published port is reachable from the
Mac at all); if it is not, `FINDINGS.md` records the negative answer and the remaining
tickets are moot. Ticket 02 is a spike whose verdict decides the topology; tickets 03 to
06 were written before the spike ran, so their acceptance criteria name services and
scrapes, never the topology.

Findings accumulate in `FINDINGS.md` in this directory from ticket 01 onwards; ticket 06
turns them into the verdict.
