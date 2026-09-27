"""日变化廓线（Diurnal Profile）数据计算。

对齐 Windographer「Diurnal Profile」：
- Single profile：每列一条 24 小时平均廓线；
- By month：每列按月各一条 24 小时廓线（col M1..M12）；
- Time Steps：每小时参与平均的非缺测样本数；
- use_common：仅使用所有选定列均有数据的时间步（listwise deletion），
  使各列均值基于同一批时间步、可直接对比。

纯计算，无 UI；filter_mask 由调用方（标记/日期/扇区过滤）构造后传入。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

HOURS = 24
_R_AIR = 287.05          # 干空气气体常数 J/(kg·K)
_RHO_STD = 1.225         # 标准空气密度 kg/m³


@dataclass
class DiurnalResult:
    """日变化廓线计算结果。"""
    labels: list[str]           # 系列标签（列名，或 `列名 M{m}`）
    means: np.ndarray           # (24, n_series) 小时均值，无样本处 NaN
    steps: np.ndarray           # (24, n_series) 每小时非缺测样本数
    by_month: bool = False
    month_of: list[int] | None = None   # 每条系列的月份（by_month 时有效）


def ti_series(df: pd.DataFrame, avg_col: str, sd_col: str) -> pd.Series:
    """湍流强度（%）：逐时间步 SD/Avg×100；Avg 非正或任一缺测 → NaN。"""
    avg = pd.to_numeric(df[avg_col], errors='coerce')
    sd = pd.to_numeric(df[sd_col], errors='coerce')
    with np.errstate(divide='ignore', invalid='ignore'):
        out = sd / avg * 100.0
    return out.where(avg.notna() & sd.notna() & (avg > 0))


def wpd_series(df: pd.DataFrame, speed_col: str,
               temp_col: str | None = None,
               pres_col: str | None = None) -> pd.Series:
    """风功率密度 (W/m²)：0.5·ρ·v³。

    ρ 优先由温度(℃)/气压(hPa)通道逐时间步计算 ρ=p/(R·T)；
    缺任一通道或结果不合理时回落标准密度 1.225 kg/m³。"""
    v = pd.to_numeric(df[speed_col], errors='coerce').clip(lower=0)
    rho: float | pd.Series = _RHO_STD
    if (temp_col and pres_col
            and temp_col in df.columns and pres_col in df.columns):
        t = pd.to_numeric(df[temp_col], errors='coerce')
        p = pd.to_numeric(df[pres_col], errors='coerce')
        rho_t = (p * 100.0) / (_R_AIR * (t + 273.15))
        # 界外视为无效（传感器坏值），该时间步回落标准密度
        rho = rho_t.where((rho_t > 0.3) & (rho_t < 2.0), _RHO_STD)
    return 0.5 * rho * v ** 3


def compute_diurnal(df: pd.DataFrame,
                    columns: list[str],
                    by_month: bool = False,
                    filter_mask: pd.Series | np.ndarray | None = None,
                    use_common: bool = False,
                    extra: dict[str, pd.Series] | None = None
                    ) -> DiurnalResult | None:
    """计算 24 小时日变化廓线。

    Parameters
    ----------
    df : 时序 DataFrame（datetime 索引）
    columns : 参与统计的列（至少一个；可为 df 实列或 extra 中的计算列）
    by_month : True 时每列按月拆分为 12 条系列
    filter_mask : 可选布尔掩码（与 df 等长），仅保留 True 行
    use_common : 仅使用所有选定列均非缺测的时间步
    extra : 计算列（如 `<列> TI`/`<列> WPD`）名 → Series，参与统一过滤与统计
    """
    if not columns:
        return None
    if extra:
        work = df.copy()
        for name, s in extra.items():
            work[name] = s
        df = work
    missing = [c for c in columns if c not in df.columns]
    if missing:
        return None
    sub = df
    if filter_mask is not None:
        mask = pd.Series(filter_mask, index=df.index).fillna(False).astype(bool)
        sub = df[mask]
        if sub.empty:
            return None

    if use_common:
        valid = sub[columns].notna().all(axis=1)
        sub = sub[valid]
        if sub.empty:
            return None

    labels: list[str] = []
    month_of: list[int] | None = [] if by_month else None
    mean_cols: list[np.ndarray] = []
    step_cols: list[np.ndarray] = []

    if not by_month:
        for col in columns:
            s = pd.to_numeric(sub[col], errors='coerce')
            g = s.groupby(s.index.hour)
            means = g.mean().reindex(range(HOURS))
            steps = g.count().reindex(range(HOURS), fill_value=0)
            labels.append(col)
            month_of = None
            mean_cols.append(means.to_numpy(dtype=float))
            step_cols.append(steps.to_numpy(dtype=float))
    else:
        for col in columns:
            s = pd.to_numeric(sub[col], errors='coerce')
            months = sorted(int(m) for m in s.index.month.unique())
            for m in months:
                sm = s[s.index.month == m]
                g = sm.groupby(sm.index.hour)
                means = g.mean().reindex(range(HOURS))
                steps = g.count().reindex(range(HOURS), fill_value=0)
                labels.append(f'{col} M{m}')
                month_of.append(m)
                mean_cols.append(means.to_numpy(dtype=float))
                step_cols.append(steps.to_numpy(dtype=float))

    if not mean_cols:
        return None
    means = np.column_stack(mean_cols)
    steps = np.column_stack(step_cols)
    return DiurnalResult(labels=labels, means=means, steps=steps,
                         by_month=by_month, month_of=month_of)
