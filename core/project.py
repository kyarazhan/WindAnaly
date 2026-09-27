"""工程会话：持有全部数据集与当前选择。

本阶段仅结构；load/open/save 等持久化待布局确认后接入 Library。
"""

import os

import pandas as pd

from core.dataset import Dataset


class Project:
    """一次分析会话的全部状态。"""

    def __init__(self):
        self.datasets: list[Dataset] = []
        self.active = -1                       # 活动数据集索引
        # 当前选择：活动通道 / 轮毂高度 / 扇区数（国内报告常用 16 扇区）
        self.selection = {
            'speed': None,       # 活动风速通道名
            'dir': None,         # 活动风向通道名
            'hub_height': 100.0,
            'sectors': 16,
        }
        # 文档历史：数据的载入/增删/标记等操作留痕（随项目文件持久化）
        self.history: list[dict] = []
        # 图表表现层配置（风玫瑰等），随项目文件持久化。
        # 与「软件默认」(core.settings.wind_rose_defaults) 区分：
        # 这里存的是本项目真正生效的值；项目无此键时才从软件默认初始化。
        self.plot_settings: dict = {}

    # ---- 文档历史 ----
    def log(self, action: str, detail: str = '', target: str = ''):
        """追加一条操作记录（文档历史窗口读取该列表）。"""
        from datetime import datetime
        self.history.append({
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'action': action,
            'target': target or (self.active_dataset.name
                                 if self.active_dataset else ''),
            'detail': detail,
        })
        return self.history[-1]

    # ---- 图表配置：项目值 ← 软件默认 ----
    def plot_setting(self, key: str) -> dict:
        """取某图表配置；返回项目值与软件默认合并后的副本（逐键防缺）。"""
        import copy
        from core import settings

        if key == 'wind_rose':
            return self.wind_rose_config()
        defaults = settings.get(key + '_defaults') if hasattr(settings, f'get_{key}_defaults') else {}
        if not isinstance(defaults, dict):
            defaults = {}
        cfg = copy.deepcopy(defaults)
        stored = self.plot_settings.get(key)
        if isinstance(stored, dict):
            cfg.update(copy.deepcopy(stored))
        return cfg

    def set_plot_setting(self, key: str, cfg: dict):
        """回写某图表配置到项目。"""
        import copy
        if key == 'wind_rose':
            self.set_wind_rose_config(cfg)
        else:
            self.plot_settings[key] = copy.deepcopy(dict(cfg or {}))

    def wind_rose_config(self) -> dict:
        """风玫瑰配置：项目有值用项目值，否则用软件默认；逐键合并防缺键。

        返回的是副本，就地修改不会生效，需调用 set_wind_rose_config() 回写。"""
        import copy

        from core import settings
        cfg = settings.get_wind_rose_defaults()
        stored = self.plot_settings.get('wind_rose')
        if not isinstance(stored, dict):
            return cfg
        cfg.update(copy.deepcopy(stored))
        styles = {}
        raw_styles = cfg.get('channel_styles') or []
        # channel_styles 在项目早期存成 list（按系列索引），Properties 对话框里
        # 是按通道名 dict。统一处理为 dict{name: merged_style}。
        if isinstance(raw_styles, list):
            for idx, st in enumerate(raw_styles):
                item = dict(settings.CHANNEL_STYLE_DEFAULTS)
                if isinstance(st, dict):
                    item.update(st)
                styles[str(idx)] = item
        elif isinstance(raw_styles, dict):
            for name, st in raw_styles.items():
                item = dict(settings.CHANNEL_STYLE_DEFAULTS)
                if isinstance(st, dict):
                    item.update(st)
                styles[name] = item
        cfg['channel_styles'] = styles
        return cfg

    def set_wind_rose_config(self, cfg: dict):
        """回写本项目的风玫瑰配置（随项目文件保存）。"""
        import copy
        self.plot_settings['wind_rose'] = copy.deepcopy(dict(cfg or {}))

    # ---- 结构操作 ----
    @property
    def active_dataset(self) -> Dataset | None:
        if 0 <= self.active < len(self.datasets):
            return self.datasets[self.active]
        return None

    def add_dataset(self, ds: Dataset):
        self.datasets.append(ds)
        self.active = len(self.datasets) - 1

    # ---- 持久化：WindAnaly 项目文件（.windrefine JSON）----
    def save_project(self, path: str, source: dict | None = None):
        """保存当前分析会话到 .windrefine 文件。

        source 记录数据来源（{'type':'file'/'library','path'/'ds_id','name'}），
        恢复时据此重新解析原始数据，再叠加通道分类与剔除标记，
        避免把整库时序写入 JSON。"""
        import json
        ds = self.active_dataset
        if ds is None:
            raise RuntimeError('无活动数据集，无法保存项目')
        payload = {
            'version': 2,
            'app': 'WindAnaly',
            'source': source or getattr(self, '_source', None),
            'selection': self.selection,
            'plot_settings': self.plot_settings,
            'import_meta': ds.import_meta,
            'dataset_name': ds.name,
            'description': ds.description,
            'attrs': ds.attrs,
            'timestamp_position': ds.timestamp_position,
            'calm_threshold': ds.calm_threshold,
            'invalid_value': ds.invalid_value,
            'channels': [
                {'name': c.name, 'kind': c.kind, 'height': c.height,
                 'units': c.units, 'role': c.role, 'color': c.color,
                 'sd_col': c.sd_col, 'max_col': c.max_col,
                 'min_col': c.min_col}
                for c in ds.channels.values()
            ],
            'calibrations': ds.calibrations,
            'flags': ds.flagged_index,
            'flag_registry': [
                {'name': f.name, 'color': f.color,
                 'include_in_calcs': f.include_in_calcs,
                 'show_in_graphs': f.show_in_graphs,
                 'favorite': f.favorite}
                for f in ds.flag_registry.values()
            ],
            'flag_masks': {
                name: [str(t) for t in s.index[s].tolist()]
                for name, s in ds.flag_masks.items()
            },
            'history': self.history,
            't_start': str(ds.df.index[0]) if len(ds.df) else None,
            't_end': str(ds.df.index[-1]) if len(ds.df) else None,
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        self._last_project_path = path

    def load_project(self, path: str):
        """从 .windrefine 文件恢复会话。

        流程：解析 source → 重建 Dataset 与通道 → 应用 import_meta 的分类/启用
        → 恢复剔除标记 → 还原 selection。"""
        import json
        from core.io_import import parse_file
        from core.dataset import Channel

        # 编码回退：.windrefine 项目文件理论上为 utf-8，
        # 但若用户误选原始数据文件（含 0xb0 等字节），友好降级而不是直接抛编码错。
        last_err = None
        for enc in ('utf-8', 'cp1252', 'gbk', 'latin-1'):
            try:
                with open(path, 'r', encoding=enc) as f:
                    p = json.load(f)
                break
            except UnicodeDecodeError as e:
                last_err = e
                continue
        else:
            raise last_err or UnicodeDecodeError(
                'utf-8', b'', 0, 1, '无法解码项目文件')
        src = p.get('source') or {}
        # 1) 重新解析原始数据
        if src.get('type') == 'library':
            from core.library import Library
            lib = Library()
            row = next((d for d in lib.list_datasets()
                        if d['id'] == src.get('ds_id')), None)
            if row is None:
                raise RuntimeError(f"库内数据集 id={src.get('ds_id')} 不存在")
            df = (lib.load_series(row['id']) if row['mode'] == 'internal'
                  else parse_file(row['path']).df)
        elif src.get('type') == 'file':
            if not os.path.exists(src.get('path', '')):
                raise RuntimeError(f"源文件不存在：{src.get('path')}")
            df = parse_file(src['path']).df
        else:
            raise RuntimeError('项目文件缺少有效 source')
        # 2) 重建 Dataset
        ds = Dataset(name=p.get('dataset_name')
                     or p.get('source', {}).get('name') or '恢复的项目')
        ds.df = df
        ds.import_meta = p.get('import_meta')
        ds.description = p.get('description', '')
        ds.attrs = p.get('attrs') or {}
        ds.timestamp_position = p.get('timestamp_position', 'start')
        ds.calm_threshold = p.get('calm_threshold', 0.0)
        ds.invalid_value = p.get('invalid_value')
        # 3) 应用通道分类 / 启用（import_meta 优先，否则用 channels 全启用）
        meta = {m['name']: m for m in (p.get('import_meta') or [])}
        chan_defs = p.get('channels') or []
        if not chan_defs and not meta:
            chan_defs = [{'name': c, 'kind': 'other'} for c in df.columns]
        enabled = []
        for ch in chan_defs:
            m = meta.get(ch['name'], {})
            enabled.append({
                'name': ch['name'],
                'kind': m.get('kind', ch.get('kind', 'other')),
                'height': m.get('height', ch.get('height')),
                'units': m.get('units', ch.get('units', '')),
                'role': m.get('role', ch.get('role', '')),
                'color': m.get('color', ch.get('color', '')),
                'sd_col': m.get('sd_col', ch.get('sd_col', '')),
                'max_col': m.get('max_col', ch.get('max_col', '')),
                'min_col': m.get('min_col', ch.get('min_col', '')),
                'enabled': m.get('enabled', True),
            })
        for ch in enabled:
            if not ch.get('enabled', True):
                continue
            ds.add_channel(Channel(
                name=ch['name'], kind=ch.get('kind', 'other'),
                height=ch.get('height'), units=ch.get('units', ''),
                role=ch.get('role', ''),
                color=ch.get('color', ''),
                sd_col=ch.get('sd_col', ''),
                max_col=ch.get('max_col', ''),
                min_col=ch.get('min_col', '')))
        # 恢复校准（兼容 v1 无校准字段）
        cals = p.get('calibrations') or {}
        for col in df.columns:
            if col not in cals:
                cals[col] = [{
                    'start': str(df.index[0]) if len(df) else None,
                    'end': str(df.index[-1]) if len(df) else None,
                    'scale': 1.0, 'offset': 0.0, 'serial': ''}]
        ds.calibrations = cals
        # 4) 恢复剔除标记（兼容旧版单一 flags 列表）
        reg = p.get('flag_registry')
        if isinstance(reg, list):
            ds.flag_registry = {}
            for item in reg:
                ds.flag_registry[item['name']] = ds.flag_registry.get(
                    item['name'], type('Flag', (), {})())
                # 用 setattr 兼容 dataclass 与旧 dict
                from core.dataset import Flag
                ds.flag_registry[item['name']] = Flag(
                    name=item['name'], color=item.get('color', '#ff6b35'),
                    include_in_calcs=item.get('include_in_calcs', False),
                    show_in_graphs=item.get('show_in_graphs', True),
                    favorite=item.get('favorite', False))
            ds._ensure_default_flags()
        masks = p.get('flag_masks')
        if isinstance(masks, dict):
            ds.flag_masks = {}
            for name, ts in masks.items():
                if name not in ds.flag_registry:
                    continue
                ts = pd.to_datetime(ts)
                m = pd.Series(df.index.isin(ts), index=df.index)
                ds.flag_masks[name] = m
            ds._update_master_flag()
        else:
            flags = p.get('flags') or []
            if flags and len(df):
                ts = pd.to_datetime(flags)
                fmask = pd.Series(df.index.isin(ts), index=df.index)
                ds.set_flag_mask(fmask)
        # 5) 还原选择与文档历史
        self.datasets.clear()
        self.add_dataset(ds)
        self.selection.update(p.get('selection', {}))
        ps = p.get('plot_settings')
        self.plot_settings = dict(ps) if isinstance(ps, dict) else {}
        hist = p.get('history')
        self.history = list(hist) if isinstance(hist, list) else []
        self._source = src
        self._last_project_path = path
        return ds

    # ---- 持久化接口（遗留契约，保留向后兼容）----
    def load_csv(self, path: str):
        """导入 CSV → 新数据集（自动列识别 + 重采样）。"""
        raise NotImplementedError('CSV 导入：待实现')

    def open_library(self):
        """从总数据库打开（库内/外链两种模式）。"""
        raise NotImplementedError('库打开：待实现')

    def save(self, mode: str = 'external'):
        """保存：mode='internal' 入总库 / 'external' 存外部文件并登记索引。"""
        raise NotImplementedError('保存：待实现')
