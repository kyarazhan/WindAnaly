"""WindAnaly 数据库导入/导出（SQL 落地实现）。

导出：活动数据集 → 台账库（masts 新站点 + datasets internal
登记 + series_<id> 时序宽表），与导入使用同一套存储约定，
导出的数据集可在「文件 → Import from Database」中直接链接载入。
"""
from __future__ import annotations

import pandas as pd

from core.library import Library


def export_dataset_to_db(ds, lib: Library | None = None,
                         station_no: str = '', location: str = '',
                         device_type: str = '', name: str = '',
                         note: str = 'WindAnaly export') -> tuple[int, str, int]:
    """把 Dataset 写入库。返回 (serial_no, 数据集名, 列数)。

    时间范围/步长/完整率从 df 推算；通道注册表写入 channels_json。
    """
    if ds is None or ds.df is None or ds.df.empty:
        raise ValueError('数据集为空，无法导出 / Empty data set')
    lib = lib or Library()
    attrs = getattr(ds, 'attrs', {}) or {}
    df = ds.df
    idx = pd.DatetimeIndex(df.index)

    t0, t1 = idx.min(), idx.max()
    t_start = (attrs.get('t_start')
               or str(pd.Timestamp(t0).date()))
    t_end = (attrs.get('t_end')
             or str(pd.Timestamp(t1).date()))

    diffs = pd.Series(idx).diff().dropna()
    dt = diffs.mode().iloc[0] if len(diffs) else pd.Timedelta(minutes=10)
    dt_min = dt.total_seconds() / 60.0
    span_min = (pd.Timestamp(t1) - pd.Timestamp(t0)).total_seconds() / 60.0
    n_expected = int(round(span_min / dt_min)) + 1 if span_min > 0 else len(df)
    completeness = round(min(len(df) / max(n_expected, 1), 1.0) * 100, 2)

    station_no = station_no or str(attrs.get('station_no') or '')
    location = location or str(attrs.get('location') or '')
    device_type = device_type or str(attrs.get('device_type') or '未知')

    serial = lib.next_serial()
    lib.add_station(serial, station_no, location, device_type,
                    str(t_start), str(t_end), completeness,
                    attrs.get('lat'), attrs.get('lon'),
                    attrs.get('elevation'))

    channels = []
    for c in ds.channels.values():
        channels.append({'name': c.name, 'kind': c.kind,
                         'height': c.height, 'units': c.units,
                         'role': c.role})
    name = name or f"{station_no or 'NA'}_{location or 'NA'}_{t_start}"
    meta = {'t_start': str(t_start), 't_end': str(t_end),
            'dt_min': dt_min, 'channels': channels,
            'coverage': completeness, 'note': note}
    ds_id = lib.register(serial, name, 'internal', meta=meta)
    lib.store_series(ds_id, df)
    return serial, name, len(ds.channels)


def import_dataset_from_db(ds_id: int, lib: Library | None = None) -> dict:
    """按 datasets.id 读回时序与元信息。

    返回 {'df', 'channels', 'rec', 'row'}；external 模式（仅外链文件路径）
    返回的 df 为 None，由上层走文件解析。
    """
    lib = lib or Library()
    rows = [d for d in lib.list_datasets() if d['id'] == ds_id]
    if not rows:
        raise ValueError(f'未找到数据集 id={ds_id}')
    row = rows[0]
    rec = lib.get_station(int(row['serial_no'])) or {}
    df = None
    if row['mode'] == 'internal':
        df = lib.load_series(ds_id)
        if df is not None:
            df.index.name = 't'   # 与 parse_file 输出保持一致
    return {'df': df, 'channels': row.get('channels') or [],
            'rec': rec, 'row': row}
