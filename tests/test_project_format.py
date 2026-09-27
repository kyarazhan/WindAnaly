"""项目文件 schema 版本化回归测试（S3-2：PROJECT_FORMAT v3 + 迁移链）。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest

from core.dataset import Channel, Dataset
from core.project import PROJECT_FORMAT, Project, migrate_payload


def test_current_format_version():
    assert PROJECT_FORMAT == 3


def _make_project():
    proj = Project()
    ds = Dataset('t')
    ds.df = pd.DataFrame({'a': [1.0]},
                         index=pd.date_range('2026-01-01', periods=1))
    ds.flags = pd.Series(False, index=ds.df.index)
    ds.channels = {'a': Channel('a', 'speed', 10, 'm/s')}
    proj.add_dataset(ds)
    return proj


def test_save_writes_v3_with_app_version(tmp_path):
    proj = _make_project()
    p = tmp_path / 'x.windanaly'
    proj.save_project(str(p), source={'type': 'file', 'path': 'a.csv',
                                      'name': 'a'})
    payload = json.loads(p.read_text(encoding='utf-8'))
    assert payload['version'] == 3
    assert payload['app'] == 'WindAnaly'
    assert isinstance(payload['app_version'], str)


def test_migrate_v1_to_current():
    v1 = {'app': 'WindRefine', 'dataset_name': 'x'}   # 无 version 字段
    out = migrate_payload(dict(v1))
    assert out['version'] == 3
    for key in ('history', 'flag_masks', 'flag_registry', 'plot_settings',
                'selection', 'app_version'):
        assert key in out, key


def test_migrate_v2_to_current():
    v2 = {'version': 2, 'history': [{'a': 1}]}
    out = migrate_payload(dict(v2))
    assert out['version'] == 3
    assert 'app_version' in out
    assert out['history'] == [{'a': 1}]       # 迁移不破坏既有数据


def test_migrate_idempotent_on_current():
    cur = {'version': 3, 'app_version': '1.0.2'}
    assert migrate_payload(dict(cur)) == cur


def test_migrate_rejects_future_version():
    with pytest.raises(ValueError):
        migrate_payload({'version': 99})
