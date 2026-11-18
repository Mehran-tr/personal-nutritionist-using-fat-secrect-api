# ADR 0001: fatsecret is a data provider, not our system of record

**Status:** accepted

## Context
fatsecret offers both a food database and profile-based features (food diary,
weight tracking) behind 3-legged OAuth 1.0.

## Decision
We use fatsecret **only** for food data (search, get, barcode, later NLP/image),
via OAuth 2.0 client credentials. Users, diaries, targets and coaching live in
our own PostgreSQL. Diary entries store a `FoodRef` (provider + external id)
**and a snapshot of the nutrients at the time of logging**.

## Consequences
+ No vendor lock-in for user data. A second provider (USDA, Open Food Facts) is
  a new `FoodProvider` adapter.
+ History stays correct if upstream data changes. Daily summaries need no API calls.
+ Simpler auth: no per-user tokens to store.
− We build the diary ourselves (we would anyway, for the coach).
