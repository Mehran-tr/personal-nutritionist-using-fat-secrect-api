import pytest

from nutritionist.modules.catalog.domain.errors import InvalidBarcodeError, InvalidSearchError
from nutritionist.modules.catalog.domain.models import Gtin, Page, SearchQuery
from tests.fakes import make_food


class TestGtin:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("4006381333931", "4006381333931"),  # EAN-13
            ("036000291452", "0036000291452"),  # UPC-A -> padded
            ("96385074", "0000096385074"),  # EAN-8 -> padded
            (" 4006-3813 33931 ", "4006381333931"),  # separators tolerated
        ],
    )
    def test_normalises_valid_codes_to_gtin13(self, raw: str, expected: str) -> None:
        assert Gtin(raw).value == expected

    @pytest.mark.parametrize("raw", ["", "abc", "1234567", "12345678901234", "4006381333932"])
    def test_rejects_invalid_codes(self, raw: str) -> None:
        with pytest.raises(InvalidBarcodeError):
            Gtin(raw)


class TestSearchQuery:
    def test_normalises_whitespace(self) -> None:
        assert SearchQuery("  greek   yogurt ").text == "greek yogurt"

    @pytest.mark.parametrize(
        ("text", "page", "page_size"),
        [("a", 0, 20), ("eggs", -1, 20), ("eggs", 0, 0), ("eggs", 0, 51)],
    )
    def test_rejects_invalid_input(self, text: str, page: int, page_size: int) -> None:
        with pytest.raises(InvalidSearchError):
            SearchQuery(text, page=page, page_size=page_size)


class TestFoodAndPage:
    def test_default_serving_prefers_flagged_serving(self) -> None:
        food = make_food()
        assert food.default_serving is food.servings[0]

    @pytest.mark.parametrize(("page", "total", "has_next"), [(0, 21, True), (1, 40, False)])
    def test_page_has_next(self, page: int, total: int, has_next: bool) -> None:
        assert Page(items=(), page=page, page_size=20, total=total).has_next is has_next
