"""Appdetails price_overview uses `initial` and `final`, not `*_price`."""
from backend import scanner


def test_limited_free_game_is_detected():
    data = {
        "type": "game", "is_free": False,
        "price_overview": {"currency": "CNY", "initial": 9900, "final": 0, "discount_percent": 100},
    }
    assert scanner.evaluate_game(data)[0] == "limited_free"


def test_paid_game_is_not_misclassified_as_free():
    data = {"type": "game", "price_overview": {"initial": 4900, "final": 2450}}
    assert scanner.evaluate_game(data)[0] == "paid"


def test_missing_price_is_unknown_without_explicit_is_free():
    assert scanner.evaluate_game({"type": "game"})[0] == "unknown"
    assert scanner.evaluate_game({"type": "game", "price_overview": {}})[0] == "unknown"


def test_explicitly_free_to_play():
    assert scanner.evaluate_game({"type": "game", "is_free": True})[0] == "permanent_free"


def test_discounted_paid_dlc_is_skipped():
    data = {"type": "dlc", "price_overview": {"initial": 1200, "final": 600}}
    assert scanner.evaluate_dlc(data, [42], {42})[0] == "skipped"


def test_limited_free_dlc_is_not_permanent_free():
    data = {"type": "dlc", "price_overview": {"initial": 1200, "final": 0}}
    assert scanner.evaluate_dlc(data, [42], {42})[0] == "skipped"


def test_no_price_dlc_needs_confirmation_unless_explicitly_free():
    assert scanner.evaluate_dlc({"type": "dlc"}, [42], {42})[0] == "unknown"
    assert scanner.evaluate_dlc({"type": "dlc", "is_free": True}, [42], {42})[0] == "claimable"


def test_unowned_parent_not_claimable():
    assert scanner.evaluate_dlc({"type": "dlc", "is_free": True}, [42], set())[0] == "skipped"
