"""When Steam store details are missing, do not suggest removing licenses."""
from backend import cleaner


def test_missing_store_details_are_not_assumed_delisted_or_free():
    meta = cleaner._classify(None, 10)
    assert meta['details_known'] is False
    assert meta['delisted'] == 0
    assert meta['price_known'] is False


def test_original_paid_price_blocks_removal_even_on_free_promo():
    meta = cleaner._classify({'type': 'game', 'price_overview': {'initial': 10000, 'final': 0}}, 10)
    assert meta['paid'] is True
    assert meta['price_initial'] == 10000
    assert meta['price_final'] == 0


def test_incomplete_price_data_not_assumed_free():
    meta = cleaner._classify({'type': 'game', 'price_overview': {'currency': 'USD'}}, 10)
    assert meta['price_known'] is False


def test_explicitly_free_item_can_be_classified():
    meta = cleaner._classify({'type': 'game', 'is_free': True}, 10)
    assert meta['price_known'] is True
    assert meta['paid'] is False
