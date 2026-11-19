from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from nutritionist.api.security import CurrentUserId
from nutritionist.modules.targets.application.use_cases import GetTargets
from nutritionist.modules.targets.domain.models import Adjustment, MacroSplit, NutritionTargets

router = APIRouter(prefix="/me/targets", tags=["targets"])

DISCLAIMER = (
    "Estimates for healthy adults, not medical advice. If you are pregnant, "
    "breastfeeding, have a medical condition or take medication affecting appetite "
    "or metabolism, talk to a doctor or registered dietitian before changing your diet."
)


class MacrosOut(BaseModel):
    protein_g: int
    carbohydrate_g: int
    fat_g: int
    fiber_g: int


class TargetsOut(BaseModel):
    calories_kcal: int
    macros: MacrosOut
    bmr_kcal: int
    tdee_kcal: int
    formula: str
    macro_split: MacroSplit
    adjustments: list[Adjustment]
    disclaimer: str = DISCLAIMER

    @classmethod
    def from_domain(cls, targets: NutritionTargets) -> "TargetsOut":
        m = targets.macros
        return cls(
            calories_kcal=targets.calories_kcal,
            macros=MacrosOut(
                protein_g=m.protein_g,
                carbohydrate_g=m.carbohydrate_g,
                fat_g=m.fat_g,
                fiber_g=m.fiber_g,
            ),
            bmr_kcal=targets.bmr_kcal,
            tdee_kcal=targets.tdee_kcal,
            formula=targets.formula,
            macro_split=targets.macro_split,
            adjustments=list(targets.adjustments),
        )


def _get_targets(request: Request) -> GetTargets:
    use_case: GetTargets = request.app.state.container.targets
    return use_case


@router.get("", response_model=TargetsOut, summary="My daily calorie and macro targets")
async def get_targets(
    user_id: CurrentUserId,
    use_case: Annotated[GetTargets, Depends(_get_targets)],
    macro_split: Annotated[
        MacroSplit | None, Query(description="Override the split saved in your profile")
    ] = None,
) -> TargetsOut:
    return TargetsOut.from_domain(await use_case.execute(user_id, macro_split))
