"""风能与功率 - 对齐源文件「功率曲线」「机组单位千瓦扫风面积」表。

E9  = 0.5*rho*B9^3*3.1415926*(D/2)^2/1000        理论功率 kW（pi 用 3.1415926 与源表一致）
F9  = C9/E9                                       Cp = P / 理论功率
H9  = C9*(G9+1)                                   调整功率 = 原功率*(1+调整百分比)
E2(扫风) = (C2/2)^2*3.1415926                     扫风面积 m2
F2(扫风) = E2/D2                                  单位千瓦扫风面积 m2/kW
"""

import math

PI = 3.1415926  # 源 Excel 使用 3.1415926，保持数值一致


def sweep_area(diameter_m: float) -> float:
    """叶轮扫风面积 (m2)。"""
    return (diameter_m / 2.0) ** 2 * PI


def specific_sweep(diameter_m: float, power_kw: float) -> float:
    """单位千瓦扫风面积 (m2/kW)。"""
    return sweep_area(diameter_m) / power_kw


def theoretical_power(v: float, rho: float, diameter_m: float) -> float:
    """风能方程理论功率 (kW)：0.5*rho*V^3*A/1000。"""
    return 0.5 * rho * v ** 3 * PI * (diameter_m / 2.0) ** 2 / 1000.0


def power_coefficient(p_kw: float, v: float, rho: float, diameter_m: float) -> float:
    """Cp = 实际功率/理论功率。理论功率为 0 时返回 0。"""
    e = theoretical_power(v, rho, diameter_m)
    return p_kw / e if e > 0 else 0.0


def wind_power_class(wpd: float) -> str:
    """风功率密度 → 风功率等级（NREL 分级，W/m²）。"""
    if wpd < 200:
        return '1 (Poor)'
    if wpd < 300:
        return '2 (Marginal)'
    if wpd < 400:
        return '3 (Fair)'
    if wpd < 500:
        return '4 (Good)'
    if wpd < 600:
        return '5 (Very good)'
    return '6 (Excellent)'
