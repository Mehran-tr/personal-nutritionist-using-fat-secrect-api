# ADR 0004: How daily nutrition targets are computed

**Status:** accepted

## Decision
1. **BMR:** Mifflin-St Jeor (1990), behind a `BmrFormula` port. Katch-McArdle can
   be added when we collect body-fat %.
2. **TDEE:** BMR × activity factor (1.2 / 1.375 / 1.55 / 1.725 / 1.9).
3. **Goal:** lose = −min(500 kcal, 20 % of TDEE); gain = +min(300 kcal, 10 % of TDEE);
   maintain = TDEE.
4. **Floors:** never below max(1200 kcal women / 1500 kcal men, BMR). Rounded to
   10 kcal (rounded *up* when the floor applies).
5. **Macros** (strategy per `MacroSplit`):

   | Split | Protein | Fixed | Remainder |
   |---|---|---|---|
   | balanced | 1.6 g/kg | fat 30 % | carbs |
   | high_protein | 2.2 g/kg | fat 25 % | carbs |
   | low_carb | 1.8 g/kg | carbs 20 % | fat |

   Protein is capped at 35 % of energy. With BMI ≥ 30, protein uses the weight at
   BMI 25 for the same height. Fiber = 14 g per 1000 kcal.
6. Every deviation from the plain formula is returned as an `adjustment` code,
   and every response carries a medical disclaimer.

## Why computed on read, not stored
Targets are a pure function of (profile, today). Storing them would create a cache
that goes stale whenever weight, age or goal changes. When the diary needs
"what was my target on 3 March", we will snapshot targets per diary day.

## Consequences
+ Deterministic, unit-testable maths with no I/O. Reference values are pinned in tests.
− `macro_split` is a query parameter for now. Persist it as a user preference
  when the clients need it (small profile migration).
− No keto, pregnancy or medical diets. These deliberately need professional input.
