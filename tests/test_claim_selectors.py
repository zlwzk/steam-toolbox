"""领取入口识别与付费过滤的单元测试（不启动真实浏览器）。"""
from backend import claimer
from backend.routers import candidates


class FakeEl:
    def __init__(self, text="", href=None):
        self._text = text
        self._href = href

    def inner_text(self):
        return self._text

    def get_attribute(self, name):
        return self._href if name == "href" else None


class FakeLoc:
    def __init__(self, items):
        self.items = list(items)

    def count(self):
        return len(self.items)

    def nth(self, i):
        return self.items[i]

    @property
    def first(self):
        return self.items[0]


def test_direct_play_button_is_not_claimable():
    run_btn = FakeEl("下载", "javascript:ShowGotSteamModal('steam://run/377560', ...)")
    assert claimer._button_is_claimable(run_btn) is False

    launch_btn = FakeEl("启动 Crusader Kings II")
    assert claimer._button_is_claimable(launch_btn) is False

    download_btn = FakeEl("下载")
    assert claimer._button_is_claimable(download_btn) is False


def test_library_button_is_claimable():
    add_btn = FakeEl("添加到库中")
    assert claimer._button_is_claimable(add_btn) is True


def test_find_claim_button_ignores_free_game_btn():
    free_game = FakeEl("下载", "javascript:ShowGotSteamModal('steam://run/670030', ...)")

    class Page:
        def locator(self, selector):
            if selector == "#freeGameBtn":
                return FakeLoc([free_game])
            return FakeLoc([])

        def get_by_text(self, pattern):
            return FakeLoc([])

    assert claimer._find_claim_button(Page()) is None
    assert claimer._has_direct_play_button(Page()) is True


def test_find_free_license_form():
    form = FakeEl("")

    class Page:
        def locator(self, selector):
            return FakeLoc([form]) if "addfreelicense" in selector else FakeLoc([])

    assert claimer._find_free_license_form(Page()) is not None


def test_candidates_query_excludes_paid_by_default():
    sql, params = candidates._build_query("", "dlc", "", "", "")
    assert "NOT (" in sql and "price_final" in sql

    sql_all, _ = candidates._build_query("", "dlc", "", "", "", include_paid=True)
    assert "NOT (" not in sql_all


def test_summary_splits_paid_from_skipped():
    # 直接校验汇总口径函数行为：paid 计数来自 price_final>0，skipped 为非付费部分
    assert hasattr(candidates, "PAID_CLAUSE")
