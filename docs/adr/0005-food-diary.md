# ADR 0005: Food diary — snapshots, server-side lookup, frozen day targets

**Status:** accepted

## Decisions
1. **Snapshot on log.** An entry stores the provider, food id, name, brand, serving
   and that serving's nutrients *as they were when logged*, plus `servings`.
   Entry nutrients = per-serving × servings.
2. **Server-side lookup only.** The client sends `food_id`, `serving_id` and
   `servings`. Nutrients come from the catalog via the `FoodLookup` port
   (`interop/catalog_to_diary.py`). The lookup runs before the DB transaction, so
   a slow upstream never holds a connection. Upstream outage → 503, nothing written.
3. **Frozen day targets.** The first entry of a day stores that day's targets
   (`diary_day_targets`, `INSERT … ON CONFLICT DO NOTHING`). Later profile changes
   don't rewrite history. A day without a snapshot shows `current` targets and
   writes nothing on read.
4. **Logging doesn't require a profile.** Targets are simply `null` until one exists.
5. **Unknown ≠ zero.** Optional nutrients (fiber, sugar, saturated fat, sodium) stay
   `null` when the source doesn't know them. Sums add the known parts only.
6. **Day window:** up to 1 day ahead (users ahead of UTC) and 366 days back. The
   client sends the *local* day.

## Consequences
+ Correct history, fast reads (one indexed query on `(user_id, day)`), no
  dependency on fatsecret for anything but logging.
+ A second food provider only needs a catalog adapter. The diary is unchanged.
− Snapshots duplicate food data per entry (small: one row of numbers).
− A day's targets don't follow a profile change made *after* logging started that
  day. That's intended. An explicit "recalculate today" action can be added if users ask.
− Quick-add (calories without a food) and custom foods/recipes are not in yet.
