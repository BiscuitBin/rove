"""T18 regressions: one test per divergence weed or the adversarial review finds.

Each test names its finding (weed T18-<n> or review T18-1 C<n>/B<n>) and the
specification line it holds the code to; the file is hash-pinned in
.allium-loop/T18-blocks-breaker.json. Weed T18-1 (ai_tmp/T18/weed-1.md): a redirect hop
whose own robots.txt read retires the hop's host is still requested. Review T18-2 C3
(ai_tmp/review/T18-2/verdicts-conformance.md): classify_block's soft checks run on any
2xx, not only on a 200. Review T18-2 C4: a discovery fetch's redirect hop refused as an
error answer (a retired host, or robots.txt disallowing it) is not retried.
"""

import dataclasses
from pathlib import Path

import pytest

from fakes import FakeFetcher, FixedClock, html_response, redirect_response, text_response
from rovo._crawl.model import CONFIG, BlockKind, BlockVerdict, standard_policy
from rovo._crawl.run import classify_block, run_crawl
from test_pace import (
    NO_DELAY,
    PAGE_HTML,
    RETIRED,
    RETIRED_HOP_ERROR,
    RETIRED_ROBOTS,
    RETIRED_SITE,
    ROBOTS,
    SEED,
    SITE,
    failed_errors,
    lone_page,
    new_mirror,
    redirect_site,
    request,
    two_hosts,
    with_retired_host,
)

HOP_ORIGIN = f"https://{RETIRED}:8443"
HOP_PAGE = f"{HOP_ORIGIN}/guide/moved.html"
HOP_ROBOTS = f"{HOP_ORIGIN}/robots.txt"


def test_weed_1_a_hop_whose_robots_read_retires_its_host_is_never_requested(
    tmp_path: Path,
) -> None:
    """Weed T18-1: the hop's own robots.txt retires its host, so the hop is not made.

    AttemptTier guidance (crawl.allium 1636 to 1640 at 86e2ec5) and FetchRobots
    guidance (834 to 838): a hop onto a host whose breaker has tripped is not requested;
    the response is the error "redirect to a retired host", retried as any error answer
    is, so the page fails with it. The seed on docs.example redirects to a second origin
    of api.example, whose robots.txt has a Crawl-delay past the cap: reading it before
    the hop retires api.example (RetireHostOnLongCrawlDelay, any origin trips the whole
    host), and the hop then goes onto a tripped host. docs.example stays untripped, so
    each of the seed's http_attempts tries is made; the hop origin's robots.txt is read
    once and never again.
    """
    cap = standard_policy().retry_after_cap.total_seconds()
    fetcher = FakeFetcher(
        {
            ROBOTS: text_response(ROBOTS, NO_DELAY),
            RETIRED_ROBOTS: text_response(RETIRED_ROBOTS, NO_DELAY),
            HOP_ROBOTS: text_response(HOP_ROBOTS, f"User-agent: *\nCrawl-delay: {cap + 1}\n"),
            SEED: redirect_response(SEED, HOP_PAGE),
            HOP_PAGE: html_response(HOP_PAGE, PAGE_HTML.format(title="Moved", prose="Moved.")),
        }
    )
    result = two_hosts(tmp_path, fetcher)
    retired = result.run.host(RETIRED)
    assert retired is not None
    assert retired.breaker_tripped
    assert HOP_PAGE not in fetcher.requests
    assert fetcher.requests.count(HOP_ROBOTS) == 1
    assert fetcher.requests.count(SEED) == CONFIG.http_attempts
    assert failed_errors(result) == {SEED: RETIRED_HOP_ERROR}


LOGIN_WALL = '<form><input type="text" name="user"><input type="password" name="pw"></form>'
MEDIAN = 1000.0
THIN = int(MEDIAN * CONFIG.soft_block_ratio) - 1


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        pytest.param(200, BlockKind.soft, id="200"),
        pytest.param(201, BlockKind.none, id="201"),
        pytest.param(206, BlockKind.none, id="206"),
    ],
)
def test_review_2_c3_only_a_200_is_checked_for_a_soft_block(status: int, kind: BlockKind) -> None:
    """Review T18-2 C3: a login wall or a thin main text is soft on a 200 alone.

    AttemptTier guidance (crawl.allium 1600 to 1601 at 86e2ec5): "then on a 200 a main
    text under soft_block_ratio of the host's median ... or a login wall (soft)". Any
    other 2xx, here a 201 or a 206, is none, so it keeps its place in the host's text
    baseline and carries no soft flag.
    """
    walled = html_response(SEED, lone_page(extra=LOGIN_WALL), status=status)
    thin = dataclasses.replace(html_response(SEED, lone_page(), status=status), main_text=THIN)
    for response, median in ((walled, None), (thin, MEDIAN)):
        verdict = classify_block(response, median)
        assert verdict.kind is kind
        if kind is BlockKind.none:
            assert verdict == BlockVerdict(kind=BlockKind.none, signature="")


def test_review_2_c4_a_robots_hop_onto_a_retired_host_is_retried(tmp_path: Path) -> None:
    """Review T18-2 C4: robots.txt's hop onto a tripped host is an error answer, retried.

    FetchRobots guidance (crawl.allium 834 to 845 at 86e2ec5): the hop is not requested
    and the fetch is the error "redirect to a retired host"; fetch_resource's tries are a
    page's http tries, a retryable answer (an error is one) retried while try <
    http_attempts. So robots.txt is requested http_attempts times, the hop never.
    """
    moved = f"{RETIRED_SITE}/elsewhere/robots.txt"
    fetcher = with_retired_host(
        {
            ROBOTS: redirect_response(ROBOTS, moved),
            SEED: html_response(SEED, lone_page()),
        }
    )
    two_hosts(tmp_path, fetcher)
    assert moved not in fetcher.requests
    assert fetcher.requests.count(ROBOTS) == CONFIG.http_attempts


def test_review_2_c4_a_discovery_hop_robots_disallows_is_retried(tmp_path: Path) -> None:
    """Review T18-2 C4: a sitemap's hop robots.txt disallows is an error answer, retried.

    HttpRetry guidance (crawl.allium 1742 to 1743 at 86e2ec5): a discovery try is
    retried the same way as a page's; the disallowed hop is retried under HttpRetry like
    any other error answer (T15 Open points item 5, spec bad753c). So /sitemap.xml is
    requested http_attempts times, the disallowed target never.
    """
    sitemap = f"{SITE}/sitemap.xml"
    private = f"{SITE}/guide/private/map.xml"
    fetcher = FakeFetcher(
        redirect_site(
            sitemap=redirect_response(sitemap, private),
            seed=html_response(SEED, lone_page()),
        )
    )
    run_crawl(request(new_mirror(tmp_path)), None, fetcher, FixedClock())
    assert private not in fetcher.requests
    assert fetcher.requests.count(sitemap) == CONFIG.http_attempts
