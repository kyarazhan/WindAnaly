"""核心数据模型骨架：通道注册 + 时序容器。

本阶段仅定义结构与接口契约，所有分析/变换方法留待布局确认后填充；
现有 core/ 数学函数零改动，tests/test_core.py 继续守护。
"""

from dataclasses import dataclass

import pandas as pd

# 通道类型常量
KIND_SPEED = 'speed'
KIND_DIR = 'dir'
KIND_SPEED_SD = 'speed_sd'
KIND_TEMP = 'temp'
KIND_PRES = 'pres'
KIND_RH = 'rh'
KIND_WZ = 'wz'              # 垂直风速
KIND_TI = 'ti'              # 计算列：湍流强度
KIND_SYNTH = 'synthetic'    # 外推/MCP 合成列


@dataclass
class Channel:
    """一条数据通道的元信息。"""
    name: str
    kind: str                      # KIND_* 之一
    height: float | None = None    # 标高 m
    units: str = ''                # m/s / deg / ℃ / hPa / %
    role: str = ''                 # 统计角色：Avg / SD / Min / Max / Gust
    color: str = ''                # 显示颜色，#RRGGBB
    sd_col: str = ''               # 关联标准差通道名
    max_col: str = ''              # 关联最大值通道名
    min_col: str = ''              # 关联最小值通道名


@dataclass
class Flag:
    """一种标记类型的元信息。"""
    name: str
    color: str = '#ff6b35'         # 默认显示颜色
    include_in_calcs: bool = False  # 是否参与计算
    show_in_graphs: bool = True     # 是否在图表中显示
    favorite: bool = False          # 是否为常用标记


class Dataset:
    """一个测风塔（或一批）时序数据：DataFrame + 通道注册表。"""

    def __init__(self, name: str = '未命名'):
        self.name = name
        self.df = pd.DataFrame()       # datetime 索引，列为通道名
        self.channels: dict[str, Channel] = {}
        # 剔除标记：布尔 Series，与 df 同索引，True = 已剔除（不参与分析）
        self.flags = pd.Series(dtype=bool)
        # 导入确认结果（通道分类/启用），供项目持久化
        self.import_meta: list[dict] | None = None

        # 数据集级属性（Configure Data Set 中维护）
        self.attrs: dict = {}
        self.description: str = ''
        self.timestamp_position: str = 'start'   # start / middle / end
        self.calm_threshold: float = 0.0
        self.invalid_value: float | None = None

        # 校准：通道名 -> [{start, end, scale, offset, serial}, ...]
        self.calibrations: dict[str, list[dict]] = {}

        # 标记系统：注册表 + 各标记掩码 + 主标记（任一标记为 True）
        self.flag_registry: dict[str, Flag] = {}
        self.flag_masks: dict[str, pd.Series] = {}
        self._ensure_default_flags()

    # ---- 结构操作（轻量，非计算）----
    def add_channel(self, ch: Channel):
        self.channels[ch.name] = ch

    def has_data(self) -> bool:
        return not self.df.empty

    def heights_of(self, kind: str) -> list[float]:
        """某类通道的全部标高（升序）。"""
        hs = [c.height for c in self.channels.values()
              if c.kind == kind and c.height is not None]
        return sorted(set(hs))

    # ---- 剔除标记（flags）----
    def _ensure_default_flags(self):
        """初始化常用标记类型。"""
        defaults = [
            Flag('Icing', '#ff8c00', False, True, False),
            Flag('Invalid', '#ff0000', False, False, False),
            Flag('Low quality', '#ffd700', False, True, False),
            Flag('Synthesized', '#90ee90', True, True, False),
            Flag('Tower shading', '#ff1493', False, True, False),
        ]
        for f in defaults:
            if f.name not in self.flag_registry:
                self.flag_registry[f.name] = f

    def _sync_flags(self):
        """确保 flags 与当前 df 索引对齐（缺失补 False，多余丢弃）。"""
        if self.df.empty:
            self.flags = pd.Series(dtype=bool)
            return
        if len(self.flags) != len(self.df.index) or \
                not self.flags.index.equals(self.df.index):
            self.flags = pd.Series(False, index=self.df.index)

    def _sync_flag_masks(self):
        """确保各命名标记掩码与 df 索引对齐。"""
        if self.df.empty:
            self.flag_masks = {n: pd.Series(dtype=bool)
                               for n in self.flag_registry}
            return
        for name in self.flag_registry:
            s = self.flag_masks.get(name)
            if s is None or len(s) != len(self.df.index) or \
                    not s.index.equals(self.df.index):
                self.flag_masks[name] = pd.Series(False, index=self.df.index)

    def _update_master_flag(self):
        """根据所有命名标记掩码刷新主 flags。"""
        self._sync_flag_masks()
        if self.df.empty:
            self.flags = pd.Series(dtype=bool)
            return
        master = pd.Series(False, index=self.df.index)
        for s in self.flag_masks.values():
            master = master | s.reindex(self.df.index, fill_value=False).astype(bool)
        self.flags = master

    def _to_mask_series(self, mask) -> pd.Series:
        """把布尔 Series / ndarray（对话框常用 index 比较结果）统一为
        与 df 索引对齐的布尔 Series。"""
        idx = self.df.index if not self.df.empty else pd.Index([])
        if len(idx) == 0:
            return pd.Series(dtype=bool)
        if isinstance(mask, pd.Series):
            return mask.reindex(idx, fill_value=False).astype(bool)
        return pd.Series(mask, index=idx).astype(bool)

    def apply_flag(self, name: str, mask: pd.Series | None = None):
        """为指定命名标记应用掩码；mask 为 None 时全部置 True。"""
        if name not in self.flag_registry:
            self.flag_registry[name] = Flag(name)
        self._sync_flag_masks()
        m = self._to_mask_series(mask) if mask is not None \
            else pd.Series(True, index=self.df.index)
        self.flag_masks[name] = m
        self._update_master_flag()

    def remove_flag(self, name: str, mask: pd.Series | None = None):
        """移除指定命名标记；mask 为 None 时全部清除。"""
        if name not in self.flag_registry:
            return
        self._sync_flag_masks()
        if mask is None:
            self.flag_masks[name] = pd.Series(False, index=self.df.index)
        else:
            cur = self.flag_masks[name]
            remove = self._to_mask_series(mask)
            self.flag_masks[name] = cur & (~remove)
        self._update_master_flag()

    def set_flag_range(self, start, end, flag_name: str = 'Invalid'):
        """将 [start, end] 时段内所有时间点标记为指定类型。"""
        self._sync_flags()
        mask = (self.df.index >= pd.Timestamp(start)) & \
               (self.df.index <= pd.Timestamp(end))
        self.apply_flag(flag_name, mask)

    def set_flag_mask(self, mask: pd.Series, flag_name: str = 'Invalid'):
        """按与索引对齐的布尔 Series 设置指定类型标记。"""
        self._sync_flags()
        self.apply_flag(flag_name, mask)

    def clear_flags(self):
        """清除全部剔除标记。"""
        self.flags = pd.Series(False, index=self.df.index) if not self.df.empty \
            else pd.Series(dtype=bool)
        self.flag_masks = {n: pd.Series(False, index=self.df.index)
                           if not self.df.empty else pd.Series(dtype=bool)
                           for n in self.flag_registry}

    def n_flags(self, flag_name: str | None = None) -> int:
        self._sync_flags()
        if flag_name is None:
            return int(self.flags.sum())
        self._sync_flag_masks()
        s = self.flag_masks.get(flag_name, pd.Series(dtype=bool))
        return int(s.sum())

    def valid_series(self, name: str) -> pd.Series:
        """返回剔除标记后的有效序列（已剔除行置 NaN 并 drop）。"""
        self._sync_flags()
        if name not in self.df.columns:
            return pd.Series(dtype=float)
        s = self.df[name].copy()
        if self.flags.any():
            s = s.where(~self.flags)
        return s.dropna()

    @property
    def flagged_index(self) -> list:
        """被剔除的时间点列表（供持久化）。"""
        self._sync_flags()
        return [str(t) for t in self.df.index[self.flags]]

    # ---- 分析/变换接口（本阶段仅契约，待实现）----
    def coverage(self) -> pd.Series:
        """各通道数据有效率（0~1）。"""
        if self.df.empty:
            return pd.Series(dtype=float)
        return self.df.notna().mean()

    def numeric_series(self, name: str) -> pd.Series:
        """返回某列的数值序列（无效值转为 NaN，不应用剔除标记）。"""
        if name not in self.df.columns:
            return pd.Series(dtype=float)
        return pd.to_numeric(self.df[name], errors='coerce')

    def resample_10min(self):
        """重采样到 10min 步长。"""
        raise NotImplementedError('重采样：待实现')

    def fill_gaps(self, method: str = 'linear'):
        """缺测插补。"""
        raise NotImplementedError('缺测插补：待实现')
