"""库清理边界语义与下架判定保护。

- lt/gt 的边界为包含边界（≤/≥），与界面标签「不超过/至少」一致；
- delisted 没有可核验数据来源：exclude 不产生额外排除、only 不产生候选，
  理由明确写为「暂不可判定」，不把未知伪造成已下架/未下架。
"""
from backend import cleaner


def test_time_match_lt_is_inclusive_boundary():
    rule = {"time_mode": "lt", "threshold": 5, "unit": "hour"}
    hit, why = cleaner._time_match(300, rule)  # 恰等于边界
    assert hit is True
    assert "≤" in why
    hit2, _ = cleaner._time_match(301, rule)
    assert hit2 is False


def test_time_match_gt_is_inclusive_boundary():
    rule = {"time_mode": "gt", "threshold": 5, "unit": "hour"}
    hit, why = cleaner._time_match(300, rule)  # 恰等于边界
    assert hit is True
    assert "≥" in why
    hit2, _ = cleaner._time_match(299, rule)
    assert hit2 is False


def test_time_match_range_inclusive():
    rule = {"time_mode": "range", "threshold": 1, "threshold2": 2, "unit": "hour"}
    assert cleaner._time_match(60, rule)[0] is True
    assert cleaner._time_match(120, rule)[0] is True
    assert cleaner._time_match(59, rule)[0] is False
    assert cleaner._time_match(121, rule)[0] is False


def test_time_match_never():
    hit, why = cleaner._time_match(0, {"time_mode": "never"})
    assert hit is True and why == "从未游玩"
    assert cleaner._time_match(1, {"time_mode": "never"})[0] is False


def test_classify_never_asserts_delisted_or_free():
    # 详情缺失：既不能确认已下架，也不能确认免费
    meta = cleaner._classify(None, 10)
    assert meta["delisted"] == 0
    assert meta["details_known"] is False
    assert meta["price_known"] is False


def test_classify_delisted_requires_evidence():
    # 即使详情齐全，当前实现也不臆测下架状态
    meta = cleaner._classify({"type": "game", "price_overview": {"initial": 0, "final": 0}}, 10)
    assert meta["delisted"] == 0
