# Security

## Reporting a vulnerability

Report a vulnerability privately, through GitHub's private vulnerability reporting on
this repository: the Security tab, then "Report a vulnerability". Never open a public
issue, pull request or discussion for it. Include what is affected, how to reproduce it,
and what an attacker gains.

## Supported versions

There is no supported release yet: nothing has been published, so a report concerns the
code on `main`. Once releases exist, this section will name the ones that receive fixes.

## Scope

In scope: the `rovo` package and its command line under `src/rovo/`, the build and
packaging configuration, the scripts under `scripts/`, the CI workflows and setup action
under `.github/`, and anything in the repository that could leak a credential or let an
untrusted input reach a contributor's machine or CI.

Out of scope: vulnerabilities in a dependency itself, which belong to that project
(though a report that `uv.lock` pins a vulnerable version is welcome), and in the shared
`biscuit-games-tooling` checkers, which belong to their own repository.
