"""The crawl's values, entities and enumerations (crawl.allium).

Entities are mutable dataclasses compared by identity; values are frozen and compared
by value. A relationship the specification declares is a list on the owning entity.
"""

import enum
import hashlib
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from protego import Protego

from rovo._mirror.model import Mirror, Operator, Tier
from rovo._mirror.urls import hostname_of

if TYPE_CHECKING:
    from rovo._crawl.pace import Timer

_OK = range(200, 300)
_NOT_MODIFIED = 304
_ABSENT = frozenset({404, 410})
_ACCESS_REFUSED = frozenset({401, 403, 429})
_TOO_MANY_REQUESTS = 429
_SERVER_ERROR = 500
_HTML_TYPES = ("text/html", "application/xhtml+xml")
# The error of a redirect hop not requested because its host had tripped.
RETIRED_HOP = "redirect to a retired host"


class RunKind(enum.Enum):
    """initial: the mirror held no page; update otherwise."""

    initial = "initial"
    update = "update"


class RunMode(enum.Enum):
    """A standard run, or an owner-testing run."""

    standard = "standard"
    owner_testing = "owner_testing"


class DiscoverySource(enum.Enum):
    """How an identity was discovered."""

    start = "start"
    sitemap = "sitemap"
    llms_txt = "llms_txt"
    link = "link"
    navigation = "navigation"
    recheck = "recheck"
    named = "named"


class FrontierStatus(enum.Enum):
    """FrontierEntry.status; rows persist across runs, so no status is terminal."""

    pending = "pending"
    in_progress = "in_progress"
    done = "done"
    unchanged = "unchanged"
    duplicate = "duplicate"
    absent = "absent"
    blocked = "blocked"
    failed = "failed"
    skipped_robots = "skipped_robots"
    skipped_blocked = "skipped_blocked"
    skipped_limit = "skipped_limit"
    skipped_not_html = "skipped_not_html"


class BlockKind(enum.Enum):
    """What block classification says."""

    none = "none"
    hard = "hard"
    challenge = "challenge"
    soft = "soft"


class RenderReason(enum.Enum):
    """Why an unblocked HTTP answer still needs a browser."""

    spa_shell = "spa_shell"
    noscript_needs_js = "noscript_needs_js"
    main_selector_absent = "main_selector_absent"
    thin_text = "thin_text"


class RedirectStop(enum.Enum):
    """Why a redirect was not followed."""

    out_of_scope = "out_of_scope"
    loop = "loop"
    hop_limit = "hop_limit"


class RobotsMode(enum.Enum):
    """Respect robots.txt, or ignore it (owner testing only)."""

    respect = "respect"
    ignore = "ignore"


class RobotsStance(enum.Enum):
    """What a robots.txt fetch resolved to."""

    rules = "rules"
    disallow_all = "disallow_all"
    allow_all = "allow_all"


class RenderMode(enum.Enum):
    """When the browser tier may render."""

    auto = "auto"
    never = "never"
    always = "always"


class StealthMode(enum.Enum):
    """Whether the stealth tier is configured."""

    off = "off"
    on = "on"


class DiscoveryProblem(enum.Enum):
    """A problem discovery reports."""

    robots_refused = "robots_refused"
    robots_unreachable = "robots_unreachable"
    sitemap_unavailable = "sitemap_unavailable"
    sitemap_unreachable = "sitemap_unreachable"
    not_a_sitemap = "not_a_sitemap"


class RunStatus(enum.Enum):
    """Run.status."""

    running = "running"
    finished = "finished"
    interrupted = "interrupted"


class BreakerStatus(enum.Enum):
    """Breaker.status."""

    watching = "watching"
    tripped = "tripped"


class WalkStatus(enum.Enum):
    """LadderWalk.status."""

    walking = "walking"
    settled = "settled"


@dataclass(frozen=True, kw_only=True)
class CrawlConfig:
    """crawl.allium's config block."""

    max_pages: int
    max_bytes: int
    sitemap_max_children: int
    sitemap_cap_multiplier: int
    sitemap_depth: int
    llms_txt_depth: int
    discovery_max_redirects: int
    observed_url_retention_syncs: int
    start_priority: int
    recheck_priority: int
    sitemap_priority: int
    llms_txt_priority: int
    link_priority: int
    deferred_priority: int
    batch_lookahead: int
    rate_per_host: float
    concurrency_per_host: int
    fetch_timeout: timedelta
    http_attempts: int
    backoff_base: timedelta
    max_backoff: timedelta
    backoff_jitter: float
    retry_after_cap: timedelta
    owner_challenge_timeout: timedelta
    min_host_rate: float
    render_min_text_chars: int
    render_max_wait: timedelta
    large_raw_html: int
    reprobe_every_syncs: int
    breaker_window: int
    block_rate_threshold: float
    breaker_pause: timedelta
    breaker_min_outcomes: int
    soft_block_ratio: float
    soft_render_gain: float
    median_min_pages: int
    host_text_history: int


# crawl.allium's config block (crawl.allium 555 to 600), the one copy in code.
CONFIG = CrawlConfig(
    max_pages=5000,
    max_bytes=2_147_483_648,
    sitemap_max_children=40,
    sitemap_cap_multiplier=4,
    sitemap_depth=1,
    llms_txt_depth=1,
    discovery_max_redirects=5,
    observed_url_retention_syncs=3,
    start_priority=100,
    recheck_priority=90,
    sitemap_priority=50,
    llms_txt_priority=40,
    link_priority=0,
    deferred_priority=-1,
    batch_lookahead=4,
    rate_per_host=2.0,
    concurrency_per_host=4,
    fetch_timeout=timedelta(seconds=30),
    http_attempts=5,
    backoff_base=timedelta(seconds=1),
    max_backoff=timedelta(seconds=16),
    backoff_jitter=0.25,
    retry_after_cap=timedelta(seconds=120),
    owner_challenge_timeout=timedelta(minutes=5),
    min_host_rate=0.05,
    render_min_text_chars=200,
    render_max_wait=timedelta(seconds=20),
    large_raw_html=5120,
    reprobe_every_syncs=5,
    breaker_window=50,
    block_rate_threshold=0.20,
    breaker_pause=timedelta(seconds=30),
    breaker_min_outcomes=10,
    soft_block_ratio=0.10,
    soft_render_gain=2.0,
    median_min_pages=5,
    host_text_history=100,
)


@dataclass(frozen=True, kw_only=True)
class CrawlPolicy:
    """A politeness snapshot, immutable for the lifetime of a run."""

    robots: RobotsMode
    honor_crawl_delay: bool
    rate_per_host: float | None
    concurrency_per_host: int | None
    retry_backoff: bool
    backoff_base: timedelta
    max_backoff: timedelta
    honor_retry_after: bool
    retry_after_cap: timedelta
    breaker_enabled: bool
    breaker_pause: timedelta
    protection_escalation: bool
    interactive_challenges: bool
    challenge_timeout: timedelta

    @property
    def is_standard(self) -> bool:
        """Every control enabled, robots respected, no escalation, no challenges."""
        return (
            self.robots is RobotsMode.respect
            and self.honor_crawl_delay
            and self.rate_per_host is not None
            and self.concurrency_per_host is not None
            and self.retry_backoff
            and self.honor_retry_after
            and self.breaker_enabled
            and not self.protection_escalation
            and not self.interactive_challenges
        )


def standard_policy() -> CrawlPolicy:
    """The standard policy: every control enabled and crawl's defaults for every number."""
    return CrawlPolicy(
        robots=RobotsMode.respect,
        honor_crawl_delay=True,
        rate_per_host=CONFIG.rate_per_host,
        concurrency_per_host=CONFIG.concurrency_per_host,
        retry_backoff=True,
        backoff_base=CONFIG.backoff_base,
        max_backoff=CONFIG.max_backoff,
        honor_retry_after=True,
        retry_after_cap=CONFIG.retry_after_cap,
        breaker_enabled=True,
        breaker_pause=CONFIG.breaker_pause,
        protection_escalation=False,
        interactive_challenges=False,
        challenge_timeout=CONFIG.owner_challenge_timeout,
    )


@dataclass(frozen=True, kw_only=True)
class BlockVerdict:
    """What block classification says about one response."""

    kind: BlockKind
    signature: str

    @property
    def counts_against_host(self) -> bool:
        """A hard block or a challenge."""
        return self.kind in {BlockKind.hard, BlockKind.challenge}


@dataclass(frozen=True, kw_only=True)
class SiteResponse:
    """One answer from the site to one attempt."""

    status: int
    source_url: str
    markup: str
    size: int
    error: str | None = None
    redirect_hops: tuple[str, ...] = ()
    redirect_location: str | None = None
    redirect_stop: RedirectStop | None = None
    content_type: str | None = None
    retry_after: timedelta | None = None
    etag: str | None = None
    last_modified: str | None = None
    main_text: int = 0
    # The raw Location header of a 3xx answer, as the fetcher read it; the follower's input.
    location: str | None = None

    @property
    def ok(self) -> bool:
        """No error and a 2xx status."""
        return self.error is None and self.status in _OK

    @property
    def not_modified(self) -> bool:
        """A 304."""
        return self.status == _NOT_MODIFIED

    @property
    def unfollowed_redirect(self) -> bool:
        """A redirect location is set."""
        return self.redirect_location is not None

    @property
    def redirected_out(self) -> bool:
        """An unfollowed redirect stopped because it left the scope."""
        return self.unfollowed_redirect and self.redirect_stop is RedirectStop.out_of_scope

    @property
    def absent(self) -> bool:
        """A 404 or 410."""
        return self.status in _ABSENT

    @property
    def access_refused(self) -> bool:
        """A 401, 403 or 429."""
        return self.status in _ACCESS_REFUSED

    @property
    def server_error(self) -> bool:
        """A 5xx."""
        return self.status >= _SERVER_ERROR

    @property
    def retryable(self) -> bool:
        """An error, a 429 or a 5xx."""
        return self.error is not None or self.status == _TOO_MANY_REQUESTS or self.server_error

    @property
    def is_html(self) -> bool:
        """No content type, or one that declares HTML."""
        return self.content_type is None or self.content_type.lower().startswith(_HTML_TYPES)

    @property
    def raw_digest(self) -> str:
        """The lowercase SHA-256 hex of the markup."""
        return hashlib.sha256(self.markup.encode()).hexdigest()


@dataclass(frozen=True, kw_only=True)
class SitemapEntry:
    """One <url> or <sitemap> child of a sitemap document."""

    loc: str
    lastmod: str | None


@dataclass(kw_only=True, eq=False)
class Frontier:
    """The persisted crawl state of one mirror."""

    mirror: Mirror
    entries: list["FrontierEntry"] = field(default_factory=list)
    observed_urls: list["ObservedUrl"] = field(default_factory=list)
    sitemap_snapshots: list["SitemapSnapshot"] = field(default_factory=list)
    tier_hints: list["TierHint"] = field(default_factory=list)

    @property
    def pending_entries(self) -> list["FrontierEntry"]:
        """Entries whose status is pending."""
        return self._with_status({FrontierStatus.pending})

    @property
    def in_progress_entries(self) -> list["FrontierEntry"]:
        """Entries whose status is in_progress."""
        return self._with_status({FrontierStatus.in_progress})

    @property
    def retry_entries(self) -> list["FrontierEntry"]:
        """Entries failed, blocked or skipped for a reason a later run may clear."""
        return self._with_status(
            {
                FrontierStatus.failed,
                FrontierStatus.blocked,
                FrontierStatus.skipped_robots,
                FrontierStatus.skipped_blocked,
                FrontierStatus.skipped_limit,
            }
        )

    @property
    def batch_idle(self) -> bool:
        """No entry is in progress."""
        return not self.in_progress_entries

    def _with_status(self, statuses: set["FrontierStatus"]) -> list["FrontierEntry"]:
        return [entry for entry in self.entries if entry.status in statuses]

    def entry(self, identity: str) -> "FrontierEntry | None":
        """FrontierEntry{frontier: this, identity: identity}."""
        return next((entry for entry in self.entries if entry.identity == identity), None)


@dataclass(kw_only=True, eq=False)
class TierHint:
    """The starting tier learned for a host and path pattern; never http."""

    frontier: Frontier
    host_name: str
    path_pattern: str
    tier: Tier
    learned_in_run: int

    def reprobe_due(self, run_id: int) -> bool:
        """run_id - learned_in_run >= config.reprobe_every_syncs: probe http again."""
        return run_id - self.learned_in_run >= CONFIG.reprobe_every_syncs


@dataclass(kw_only=True, eq=False)
class FrontierEntry:
    """One queue row per identity ever discovered."""

    frontier: Frontier
    identity: str
    depth: int
    discovered_via: DiscoverySource
    discovered_from: str | None
    sitemap_lastmod: str | None
    priority: int
    attempts: int
    status: FrontierStatus

    @property
    def host_name(self) -> str:
        """hostname_of(identity)."""
        return hostname_of(self.identity)

    @property
    def is_deferred(self) -> bool:
        """The priority is below zero."""
        return self.priority < 0


@dataclass(kw_only=True, eq=False)
class ObservedUrl:
    """A URL seen in a sitemap or llms.txt, in scope or not."""

    frontier: Frontier
    url: str
    sources: frozenset[DiscoverySource]
    last_seen_run: int


@dataclass(kw_only=True, eq=False)
class SitemapSnapshot:
    """The validators and entries of a sitemap last read, saved in .rovo/sitemaps.json."""

    frontier: Frontier
    url: str
    etag: str | None
    last_modified: str | None
    is_index: bool
    entries: tuple[SitemapEntry, ...]
    last_requested_run: int


@dataclass(kw_only=True, eq=False)
class Run:
    """One sync run."""

    target: Mirror
    operator: Operator
    id: int
    kind: RunKind
    mode: RunMode
    baseline: "Run | None"
    preceding: "Run | None"
    scope_hash: str
    owned_hosts: frozenset[str]
    requested_owner_test: None
    policy: CrawlPolicy
    dry_run: bool
    interactive: bool
    render_mode: RenderMode
    stealth_mode: StealthMode
    max_age: timedelta | None
    refollow_unchanged_links: bool
    targets: frozenset[str]
    forced_refetch: frozenset[str]
    active_urls: frozenset[str]
    recheckable_urls: frozenset[str]
    unresolved_urls: frozenset[str]
    error: str | None
    interrupt_requested: bool
    crawling: bool
    budget_stopped: bool
    bytes_fetched: int
    fetch_attempts: int
    started_at: datetime
    status: RunStatus
    finished_at: datetime | None = None
    hosts: list["Host"] = field(default_factory=list)
    robots_policies: list["RobotsPolicy"] = field(default_factory=list)
    # Implementation state, not specification fields: the timer the run paces on, the
    # jitter draw retry_wait scales a backoff by (a factor in [low, high]), and the
    # DiscoveryFailed and HostBackedOff events raised so far, which CrawlResult returns;
    # the sitemaps read this run (FetchSitemap reads each at most once), the frontier's
    # row count when discovery ended (rovo.allium CloseRun's discovered_count), and the
    # limiter of each host name a robots.txt hop reached before OpenHost opened it; the
    # UrlBlocked, UrlSkippedBlocked and BreakerTripped events raised so far, which
    # CrawlResult returns; and the root's sinks: its progress sink (start and page), its
    # AnnounceBackoff, which the run hands each HostBackedOff as it is raised, and its
    # AnnounceTrip, which it hands each BreakerTripped.
    timer: "Timer" = field(repr=False)
    draw: Callable[[float, float], float] = field(repr=False)
    discovery_failures: list["DiscoveryFailed"] = field(default_factory=list, repr=False)
    backoffs: list["HostBackedOff"] = field(default_factory=list, repr=False)
    sitemaps_read: set[str] = field(default_factory=set, repr=False)
    discovered_count: int = field(default=0, repr=False)
    pending_limiters: dict[str, "Host"] = field(default_factory=dict, repr=False)
    progress: Callable[["ProgressEvent"], None] | None = field(default=None, repr=False)
    on_backoff: Callable[["HostBackedOff"], None] | None = field(default=None, repr=False)
    blocks: list["UrlBlocked"] = field(default_factory=list, repr=False)
    skips: list["UrlSkippedBlocked"] = field(default_factory=list, repr=False)
    trips: list["BreakerTripped"] = field(default_factory=list, repr=False)
    on_trip: Callable[["BreakerTripped"], None] | None = field(default=None, repr=False)

    @property
    def tripped_hosts(self) -> list["Host"]:
        """Hosts whose breaker tripped."""
        return [host for host in self.hosts if host.breaker_tripped]

    @property
    def has_tripped_host(self) -> bool:
        """A host's breaker tripped."""
        return bool(self.tripped_hosts)

    @property
    def targeted(self) -> bool:
        """A standard run with operator-named targets."""
        return self.mode is RunMode.standard and bool(self.targets)

    @property
    def is_owner_testing(self) -> bool:
        """The run is in owner-testing mode."""
        return self.mode is RunMode.owner_testing

    @property
    def usable_tiers(self) -> tuple[Tier, ...]:
        """The tiers this run may walk."""
        if self.render_mode is RenderMode.never:
            return (Tier.http,)
        if (
            self.is_owner_testing
            and self.policy.protection_escalation
            and self.stealth_mode is StealthMode.on
        ):
            return (Tier.http, Tier.browser, Tier.stealth)
        return (Tier.http, Tier.browser)

    @property
    def highest_tier(self) -> Tier:
        """The last usable tier."""
        return self.usable_tiers[-1]

    @property
    def page_budget_remaining(self) -> int:
        """max(0, config.max_pages - fetch_attempts)."""
        return max(0, CONFIG.max_pages - self.fetch_attempts)

    @property
    def byte_budget_left(self) -> bool:
        """bytes_fetched < config.max_bytes."""
        return self.bytes_fetched < CONFIG.max_bytes

    def host(self, name: str) -> "Host | None":
        """Host{run: this, name: name}."""
        return next((host for host in self.hosts if host.name == name), None)

    def robots_policy(self, origin: str) -> "RobotsPolicy | None":
        """RobotsPolicy{run: this, origin: origin}."""
        return next((p for p in self.robots_policies if p.origin == origin), None)


@dataclass(kw_only=True, eq=False)
class Breaker:
    """The per-host circuit breaker."""

    host: "Host"
    tier: Tier
    highest_tier: Tier
    outcomes: list[bool]
    escalations: int
    since_escalation: int
    status: BreakerStatus

    @property
    def block_rate(self) -> float:
        """blocked_share(outcomes): the share of outcomes counted as a block, 0 when none."""
        return sum(self.outcomes) / len(self.outcomes) if self.outcomes else 0.0

    @property
    def over_threshold(self) -> bool:
        """Enough outcomes, and a block rate past block_rate_threshold."""
        return (
            len(self.outcomes) >= min(CONFIG.breaker_window, CONFIG.breaker_min_outcomes)
            and self.block_rate > CONFIG.block_rate_threshold
        )

    @property
    def should_act(self) -> bool:
        """Watching, over the threshold, and not waiting out an escalation."""
        return (
            self.status is BreakerStatus.watching
            and self.over_threshold
            and (
                self.tier is not self.highest_tier
                or self.escalations == 0
                or self.since_escalation >= CONFIG.breaker_window
            )
        )


@dataclass(kw_only=True, eq=False)
class Host:
    """A host as seen by one run."""

    run: Run
    name: str
    origin: str
    rate: float | None
    crawl_delay: timedelta
    paused_until: datetime | None
    recent_text_lengths: list[int]
    tiers_used: frozenset[Tier]
    fetched: int
    blocked: int
    render_escalations: int
    retry_after_honored: int
    sitemap_children_read: int
    sitemap_entries_admitted: int
    breaker: Breaker | None = None
    # Implementation state beside paused_until: when the last request to the host name
    # started, from which the limiter spaces the next one (crawl.allium AttemptTier).
    last_started: datetime | None = field(default=None, repr=False)

    @property
    def median_text(self) -> float:
        """The median of the recent main-text sizes."""
        return (
            float(statistics.median(self.recent_text_lengths)) if self.recent_text_lengths else 0.0
        )

    @property
    def has_text_baseline(self) -> bool:
        """Enough recent pages for a median."""
        return len(self.recent_text_lengths) >= CONFIG.median_min_pages

    @property
    def breaker_tripped(self) -> bool:
        """The breaker's status is tripped."""
        return self.breaker is not None and self.breaker.status is BreakerStatus.tripped

    @property
    def block_rate(self) -> float:
        """Blocked over fetched, 0 when nothing was fetched."""
        return self.blocked / self.fetched if self.fetched > 0 else 0.0


@dataclass(kw_only=True, eq=False)
class RobotsPolicy:
    """The robots stance of one origin for one run."""

    run: Run
    origin: str
    stance: RobotsStance
    crawl_delay: timedelta | None
    declared_sitemaps: tuple[str, ...]
    problem: DiscoveryProblem | None
    rules: Protego | None = field(default=None, repr=False)
    # The rovo group's Crawl-delay as written, an exact decimal number of seconds:
    # implementation state for robots_crawl_delay_exceeds, which never builds a Duration.
    declared_delay: Decimal | None = field(default=None, repr=False)


@dataclass(kw_only=True, eq=False)
class LadderWalk:
    """One entry's walk up the tiers."""

    entry: FrontierEntry
    host: Host
    tiers: tuple[Tier, ...]
    conditional: bool
    escalated: bool
    challenge_offered: bool
    status: WalkStatus
    standing: "FetchAttempt | None" = None
    attempts: list["FetchAttempt"] = field(default_factory=list)

    @property
    def soft_suspect(self) -> list["FetchAttempt"]:
        """The attempts with a soft verdict and no render reason."""
        return [
            attempt
            for attempt in self.attempts
            if attempt.verdict.kind is BlockKind.soft and attempt.render_reason is None
        ]

    @property
    def ok_http(self) -> list["FetchAttempt"]:
        """The ok, unblocked http attempts."""
        return [
            attempt
            for attempt in self.attempts
            if attempt.tier is Tier.http
            and attempt.response.ok
            and attempt.verdict.kind is BlockKind.none
        ]

    @property
    def render_needed(self) -> bool:
        """The standing attempt has a render reason."""
        return self.standing is not None and self.standing.render_reason is not None


@dataclass(kw_only=True, eq=False)
class FetchAttempt:
    """One try at one tier."""

    walk: LadderWalk
    tier: Tier
    try_: int
    response: SiteResponse
    verdict: BlockVerdict
    render_reason: RenderReason | None
    # OwnerChallenge rows exist only in an owner-testing run (a later slice), so none here.
    challenges: list[object] = field(default_factory=list, repr=False)

    @property
    def unsuccessful_challenge(self) -> bool:
        """A challenge of this attempt was abandoned or timed out; none is offered yet."""
        return False

    @property
    def retires_host(self) -> bool:
        """A Retry-After past the cap retires the host, whatever the tier (a render's too)."""
        policy = self.walk.host.run.policy
        return (
            self.response.retryable
            and self.response.retry_after is not None
            and policy.honor_retry_after
            and self.response.retry_after > policy.retry_after_cap
        )

    @property
    def retryable(self) -> bool:
        """An http answer worth another try."""
        return (
            self.tier is Tier.http
            and self.response.retryable
            and self.try_ < CONFIG.http_attempts
            and not self.retires_host
        )

    @property
    def failed_outright(self) -> bool:
        """No response arrived."""
        return self.response.error is not None or self.response.status == 0

    @property
    def hop_refused(self) -> bool:
        """A hop fetch_or_render did not request because its host had tripped."""
        return self.response.error == RETIRED_HOP

    @property
    def wants_escalation(self) -> bool:
        """The attempt asks for the next tier."""
        return (
            (self.render_reason is not None or self.verdict.kind is not BlockKind.none)
            and (
                self.verdict.kind is BlockKind.none
                or self.walk.host.run.policy.protection_escalation
            )
            and not (self.response.ok and not self.response.is_html)
            and not self.response.not_modified
            and not self.unsuccessful_challenge
        )


@dataclass(frozen=True, kw_only=True)
class EntryFailed:
    """The EntryFailed trigger (crawl.allium EntryFails)."""

    run: Run
    entry: FrontierEntry
    error: str
    attempts: int


@dataclass(frozen=True, kw_only=True)
class UrlFailed:
    """The UrlFailed trigger EntryFails raises for the root (crawl.allium EntryFails)."""

    run: Run
    url: str
    error: str
    attempts: int


@dataclass(frozen=True, kw_only=True)
class DiscoveryFailed:
    """The DiscoveryFailed trigger (crawl.allium DenyAllWhenRobotsRefused and its kin)."""

    run: Run
    url: str
    problem: DiscoveryProblem


@dataclass(frozen=True, kw_only=True)
class HostBackedOff:
    """The HostBackedOff trigger (crawl.allium HttpRetry)."""

    host: Host
    until: datetime


@dataclass(frozen=True, kw_only=True)
class UrlSkippedBlocked:
    """The UrlSkippedBlocked trigger (SelectBatch, SkipTrippedHost and BreakerTrips)."""

    run: Run
    url: str


@dataclass(frozen=True, kw_only=True)
class UrlBlocked:
    """The UrlBlocked trigger (crawl.allium DisposeFetch's hard or challenge branch)."""

    run: Run
    url: str
    status: int
    signature: str
    tier: Tier


@dataclass(frozen=True, kw_only=True)
class BreakerTripped:
    """The BreakerTripped trigger (BreakerTrips and the two host retirements)."""

    host: Host


@dataclass(frozen=True, kw_only=True)
class ProgressEvent:
    """rovo.allium's ProgressReported, as the progress sink receives it.

    `event` is one of start, page, host_backoff, breaker_tripped, owner_testing_warning
    and done; `host` and `until` are null where the event names none, and `url` is null
    on every event but page, where it is the settled row's URL.
    """

    event: str
    host: str | None
    until: datetime | None
    url: str | None = None


@dataclass(frozen=True, kw_only=True)
class RunRequest:
    """The RunRequested trigger the root raises through SyncControl (crawl.allium 2421)."""

    operator: Operator
    mirror: Mirror
    id: int
    kind: RunKind
    mode: RunMode
    scope_hash: str
    owned_hosts: frozenset[str]
    policy: CrawlPolicy
    dry_run: bool
    interactive: bool
    render_mode: RenderMode
    stealth_mode: StealthMode
    targets: frozenset[str]
    baseline: Run | None = None
    preceding: Run | None = None
    requested_owner_test: None = None
    max_age: timedelta | None = None
    # rovo.allium's config default; StartSync always passes the configuration's value.
    refollow_unchanged_links: bool = True
