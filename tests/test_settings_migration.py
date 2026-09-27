"""设置旧键迁移的回归测试（S1：windrefine_* → analy_*）。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import settings


def test_migrate_old_keys(tmp_path, monkeypatch):
    p = tmp_path / 'settings.json'
    p.write_text(json.dumps({
        'windrefine_toolbar': ['open', 'save'],
        'windrefine_tabs_visible': ['Summary'],
        'windrefine_recent_files': [{'path': 'x', 'name': 'n', 'kind': 'file'}],
    }, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(settings, '_PATH', str(p))
    assert settings.get('analy_toolbar') == ['open', 'save']
    assert settings.get('analy_tabs_visible') == ['Summary']
    assert settings.get('analy_recent_files') == [
        {'path': 'x', 'name': 'n', 'kind': 'file'}]
    # 旧键不再暴露
    assert settings.get('windrefine_toolbar') is None


def test_migrate_prefers_new_key(tmp_path, monkeypatch):
    """新键已有值时，旧键丢弃、不覆盖新值。"""
    p = tmp_path / 'settings.json'
    p.write_text(json.dumps({
        'windrefine_toolbar': ['open'],
        'analy_toolbar': ['open', 'append'],
    }), encoding='utf-8')
    monkeypatch.setattr(settings, '_PATH', str(p))
    assert settings.get('analy_toolbar') == ['open', 'append']


def test_defaults_use_new_keys():
    assert 'analy_toolbar' in settings._DEFAULTS
    assert 'analy_tabs_visible' in settings._DEFAULTS
    assert 'analy_recent_files' in settings._DEFAULTS
    assert not any(k.startswith('windrefine_') for k in settings._DEFAULTS)


def test_quick_toolbar_default_has_no_help():
    assert 'help' not in settings.QUICK_TOOLBAR_DEFAULT
    assert 'about' in settings.QUICK_TOOLBAR_DEFAULT
