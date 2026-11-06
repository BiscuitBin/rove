# 03: Firecrawl stack up and ready

**Network:** this ticket pulls several gigabytes of container images (or their bare
equivalents, depending on ticket 02's verdict): the Firecrawl API, its browser service,
its Postgres, Redis and RabbitMQ. Ask before pulling, and record the sizes.

**What to build:** `fcproto up` brings up self-hosted Firecrawl inside the machine, in
the topology ticket 02 chose, and does not return until Firecrawl can really scrape;
`fcproto status` then shows each service's state. The demo is a `curl` from the Mac to
`127.0.0.1:3002/v2/scrape` that returns Markdown for `https://example.com`. This is the
fattest slice; split it into "stack up" and "readiness and status" if finer grain is
wanted, in that order.

The five services, pinned, in start order:

1. **Postgres** for the queue (`ghcr.io/firecrawl/nuq-postgres`; it publishes only
   `latest` and `sha-*` tags, so pin a `sha-*` tag). It needs `POSTGRES_DB=postgres` and
   an empty data directory on first start.
2. **RabbitMQ** (`rabbitmq:3-management`).
3. **Redis** (`redis:alpine`).
4. **The browser service** (`ghcr.io/firecrawl/playwright-service`; `latest` and `sha-*`
   only, so pin a `sha-*` tag). It listens on 3003 unless `PORT=3000` is set; set it, so
   that the API's default microservice URL is right. Its SSRF guard refuses private
   addresses, so every test target is public: use `https://example.com`.
5. **The API** (`ghcr.io/firecrawl/firecrawl`, version tags such as `2.11.698`; pin one).
   Its image command, `node dist/src/harness.js --start-docker`, spawns only Node
   processes (the API on 3002, workers on 3004 to 3012), but it probes for a docker or
   podman CLI, and it throws unless both `NUQ_DATABASE_URL` and `NUQ_RABBITMQ_URL` are
   set. The harness waits only for its own API port; the start order above is the
   prototype's job, not Firecrawl's.

All images are public and built for linux/arm64. Everything shares one network
namespace, so the environment is all-on-localhost:

```text
HOST=0.0.0.0
PORT=3002
USE_DB_AUTHENTICATION=false
REDIS_URL=redis://localhost:6379
REDIS_RATE_LIMIT_URL=redis://localhost:6379
NUQ_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres
NUQ_RABBITMQ_URL=amqp://localhost:5672
PLAYWRIGHT_MICROSERVICE_URL=http://localhost:3000/scrape
```

If ticket 02 chose one machine per service, "localhost" becomes whatever that verdict
says the services use to find each other; the acceptance criteria do not change.

Readiness is a real scrape, not the heartbeat: `GET /v0/health/readiness` answers as soon
as the API process is up, before the workers and the browser service can serve. `fcproto
up` is ready when `POST /v2/scrape` with the body
`{"url": "https://example.com", "formats": ["markdown"], "timeout": 60000}` and no
`Authorization` header returns `{"success": true, "data": {"markdown": ..., "metadata":
{"statusCode": ..., "sourceURL": ..., "title": ...}}}`. Call the REST API with the
standard library; the Firecrawl Python SDK's self-host base URL is unconfirmed and not
worth the dependency here. Poll with a bounded total wait and print progress, because a
cold start pulls images and a warm one does not.

Record in `FINDINGS.md`: the image sizes, the resources the machine was given, the cold
`up` time to a successful scrape, and every sharp edge met.

**Blocked by:** 02 (Topology spike).

**Status:** ready-for-agent

- [ ] `uv run fcproto up` starts Postgres, RabbitMQ, Redis, the browser service and the
  API inside the machine, in that order, with the all-on-localhost environment, and
  returns only after a scrape of `https://example.com` succeeds or a bounded wait runs
  out (then it exits non-zero and says which service it was waiting on)
- [ ] Each image or package is pinned to a version or digest, never `latest`; where the
  tag above is a floating one (`redis:alpine`, `rabbitmq:3-management`), the digest
  resolved at pull time is recorded in `FINDINGS.md`
- [ ] From the Mac, `curl -X POST 127.0.0.1:3002/v2/scrape` with a JSON body naming
  `https://example.com` and `["markdown"]` returns `"success": true` and Markdown
  containing the page's heading; the response is quoted in `FINDINGS.md`
- [ ] `uv run fcproto status`, in a fresh process, shows the machine's state and one line
  per service with whether it is running
- [ ] `uv run fcproto up` prints progress while waiting and prints the machine and service
  state when it finishes
- [ ] `FINDINGS.md` records the image sizes, the resources given to the machine, the cold
  `up` time to the first successful scrape, and every sharp edge met
- [ ] `fcproto destroy` removes the machine and everything the stack wrote
- [ ] `just check` ends with `All checks passed and the worktree is unchanged.` and
  `git status --short` is empty
