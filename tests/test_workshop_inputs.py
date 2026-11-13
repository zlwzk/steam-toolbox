"""Reject invalid job inputs before launching a browser or using a local profile."""
from backend import workshop


def test_workshop_invalid_inputs(monkeypatch):
    monkeypatch.setattr(workshop.database, 'get_settings', lambda: {'api_key': 'test', 'steamid': '76561198000000000'})
    assert workshop.start_task('not-a-number')['ok'] is False
    assert workshop.start_task('0')['ok'] is False
    assert workshop.start_task('1', mode='delete_database')['ok'] is False
    assert workshop.start_task('1', range_start=10, range_end=2)['ok'] is False
    assert workshop.start_task('1', range_start=-1)['ok'] is False
