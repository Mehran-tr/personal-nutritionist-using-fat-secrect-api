# ADR 0006: Coach — rules decide, an LLM may only rephrase

**Status:** accepted

## Context
Users want feedback on their day ("what should I change?"). An LLM writes nice
text, but it can invent numbers, give medical advice, or push unhealthy goals.
It also costs money and latency on every call.

## Decision
1. **Rules engine (domain):** small independent rules each return at most one
   `Insight` (code, severity, message, actual/target/unit). The engine ranks them
   (warning → suggestion → info, then rule order) and returns the top 5. Rules:
   nothing logged, no targets, calories over/under/very low, protein under, fiber
   under, sodium high, saturated fat high, on track, incomplete data.
2. **Day status matters:** past days are `complete`. Today is `in_progress` and
   only gets "excess" feedback.
3. **Safety:** below 60 % of the calorie target → warning that recommends a doctor
   or dietitian, worded so missed logging is not blamed. Nothing praises eating less.
4. **Optional LLM phrasing** (`COACH__LLM_ENABLED`, off by default, Anthropic
   Messages API):
   - The input is only the insights' messages and severities. No profile or body
     data, and no user-written text (so no prompt injection from user input).
   - A system prompt restricts it to rephrasing, with no medical advice and no body judgments.
   - **Number guardrail:** if the output contains any number that isn't in the
     insights, or exceeds 800 characters, it is discarded.
   - Any failure → `summary: null`. The review is complete without it.
   - Successful phrasings are cached by (prompt version, model, insights) for 7 days.

## Consequences
+ Explainable, unit-tested feedback. The LLM is an enhancement that can't
  corrupt facts, and costs about one call per distinct day.
+ New coaching behaviour = one new rule class + tests.
− The number check can't catch every wrong *qualitative* claim. The narrow input
  and system prompt limit that. Periodic review of sampled outputs is recommended
  before enabling it for all users.
− No weekly trends yet (e.g. "protein low 5 of 7 days"). That's the natural next
  rule family, built on the same summaries.
