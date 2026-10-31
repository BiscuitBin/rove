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
