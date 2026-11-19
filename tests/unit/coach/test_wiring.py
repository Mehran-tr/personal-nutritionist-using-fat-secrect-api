import httpx
import pytest
from pydantic import SecretStr
from pydantic import ValidationError as PydanticValidationError

from nutritionist.bootstrap import build_phraser
from nutritionist.core.cache import InMemoryCache
from nutritionist.core.config import CoachSettings, Settings
from nutritionist.modules.coach.application.use_cases import NoPhraser
from nutritionist.modules.coach.infrastructure.phrasers import CachedPhraser


def test_enabling_the_llm_without_a_key_fails_at_startup() -> None:
    with pytest.raises(PydanticValidationError, match="ANTHROPIC_API_KEY"):
        CoachSettings(llm_enabled=True)


@pytest.mark.parametrize(
    ("coach", "expected"),
    [
        (CoachSettings(), NoPhraser),
        (CoachSettings(llm_enabled=True, anthropic_api_key=SecretStr("sk")), CachedPhraser),
    ],
)
def test_phraser_selection(settings: Settings, coach: CoachSettings, expected: type) -> None:
    phraser = build_phraser(
        settings.model_copy(update={"coach": coach}), httpx.AsyncClient(), InMemoryCache()
    )
    assert isinstance(phraser, expected)
