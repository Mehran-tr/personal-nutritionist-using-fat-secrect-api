# ADR 0002: Modular monolith with ports & adapters, enforced by import-linter

**Status:** accepted

## Context
One small team and one deployable, but the product has clear sub-domains
(catalog, profile, targets, diary, coach) that grow at different speeds.

## Decision
Feature modules under `modules/`, each with `domain / application /
infrastructure / api` layers. Adapters are chosen only in `bootstrap.py`. Layer
rules are checked in CI with import-linter rather than by convention.

## Consequences
+ Modules can be tested in isolation and extracted into services later if needed.
+ Boundaries survive deadline pressure because CI enforces them.
− A little more ceremony than a flat `routers/ services/ models/` layout.
