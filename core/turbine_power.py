"""风机功率输出计算（对齐 Windographer 12.2 章算法）。

- 变桨控制：有效风速 U_eff = U·(ρ/ρ0)^(1/3) 后查功率曲线；
- 失速控制：P = P0·(ρ/ρ0)；
- 净输出 = 毛输出 × 综合折减系数；AEP = P_net × 8760；NCF = P_net/额定。
功率曲线为 (风速 m/s, 功率 kW) 升序点列，线性插值。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def effective_speed(u, rho: float, rho0: float):
    """变桨控制有效风速：能量等价的标准密度风速。"""
    if rho0 <= 0:
        rho0 = 1.225
    factor = (rho / rho0) ** (1.0 / 3.0)
    if np.isscalar(u):
        return float(u) * factor
    return np.asarray(u, dtype=float) * factor


def power_from_curve(curve_u, curve_p, u) -> np.ndarray:
    """查功率曲线（线性插值）；切入前 0，额定后保持额定功率。"""
    cu = np.asarray(curve_u, dtype=float)
    cp = np.asarray(curve_p, dtype=float)
    order = np.argsort(cu)
    cu, cp = cu[order], cp[order]
    scalar = np.isscalar(u)
    ua = np.atleast_1d(np.asarray(u, dtype=float))
    out = np.interp(ua, cu, cp, left=0.0, right=cp[-1])
    out[ua < cu[0]] = 0.0
    return float(out[0]) if scalar else out


def stall_power(curve_u, curve_p, u, rho: float, rho0: float):
    """失速控制：先查功率再按密度比修正。"""
    p0 = power_from_curve(curve_u, curve_p, u)
    if np.isscalar(p0):
        return float(p0) * rho / rho0
    return np.asarray(p0, dtype=float) * rho / rho0


def output_series(speed: pd.Series, curve_u, curve_p, rho: float = 1.225,
                  rho0: float = 1.225, method: str = 'pitch',
                  loss_factor: float = 1.0) -> pd.Series:
    """逐时间步功率输出（kW），返回净功率序列。"""
    u = pd.to_numeric(speed, errors='coerce')
    if method == 'stall':
        p = stall_power(curve_u, curve_p, u.to_numpy(), rho, rho0)
    else:
        u_eff = effective_speed(u.to_numpy(), rho, rho0)
        p = power_from_curve(curve_u, curve_p, u_eff)
    out = pd.Series(p, index=u.index) * float(loss_factor)
    return out


def aep_kw_hours(p_net_kw: float) -> float:
    """平均净功率 (kW) → 年净发电量 (kWh/yr)。"""
    return p_net_kw * 8760.0


def capacity_factor(p_net_kw: float, rated_kw: float) -> float:
    """净容量系数 NCF = P_net / P_rated。"""
    if rated_kw <= 0:
        return float('nan')
    return p_net_kw / rated_kw


def mean_air_density_df(df: pd.DataFrame, temp_col: str | None,
                        pres_col: str | None) -> pd.Series:
    """逐时间步空气密度 (kg/m³)；缺通道返回常数序列 1.225。"""
    _R = 287.05
    if (temp_col and pres_col and temp_col in df.columns
            and pres_col in df.columns):
        t = pd.to_numeric(df[temp_col], errors='coerce')
        p = pd.to_numeric(df[pres_col], errors='coerce')
        rho = (p * 100.0) / (_R * (t + 273.15))
        rho = rho.where((rho > 0.3) & (rho < 2.0), 1.225)
        return rho
    return pd.Series(1.225, index=df.index)


def hub_height_speed(speed: pd.Series, meas_height: float,
                     hub_height: float, alpha: float) -> pd.Series:
    """按切变指数把实测风速外推到轮毂高度。"""
    if meas_height <= 0 or meas_height == hub_height:
        return speed
    return speed * (hub_height / meas_height) ** alpha


def rating_from_curve(curve_p) -> float:
    """额定功率 = 功率曲线最大功率。"""
    cp = np.asarray(curve_p, dtype=float)
    return float(cp.max()) if cp.size else float('nan')


def monthly_energy(p_net: pd.Series) -> pd.DataFrame:
    """逐月发电量：月均净功率 × 月小时数。"""
    s = p_net.dropna()
    if s.empty:
        return pd.DataFrame(columns=['month', 'p_net', 'hours', 'energy'])
    hours = s.groupby(s.index.month).count().astype(float) / 6.0  # 10min 假设?
    # 小时数按实际样本数 × 时间步长更准：由索引差推步长（分钟）
    diffs = pd.Series(np.diff(np.asarray(s.index).astype('datetime64[s]')
                              .astype('int64')) / 60.0)
    dt_min = float(diffs.mode().iloc[0]) if not diffs.empty else 10.0
    counts = s.groupby(s.index.month).count().astype(float)
    hours = counts * dt_min / 60.0
    pmean = s.groupby(s.index.month).mean()
    return pd.DataFrame({'month': pmean.index,
                         'p_net': pmean.values,
                         'hours': hours.values,
                         'energy': (pmean * hours).values})
