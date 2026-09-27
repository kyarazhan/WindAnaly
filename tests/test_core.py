"""core 公式回归测试 - 锚点取自源 Excel 缓存值。

2026-08-28 拆分：air_density / shear / distributions / extreme_wind /
long_term / guarantee / m1_split 连同 13 个计算器页已迁至 WindAnaly
（风资源小工具箱），那 9 项回归随之迁走。此处只保留两边共用的
wind_power —— 它同时服务于本项目的分析与 WindAnaly 的功率曲线工具。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.wind_power import (power_coefficient, sweep_area,
                                     theoretical_power)


def approx(a, b, tol=1e-6):
    assert abs(a - b) < tol, f'{a} != {b}'


def test_sweep():
    # D=150 => E=17671.458
    approx(sweep_area(150), 17671.458375000002, 1e-6)


def test_power_curve():
    # rho=1.225, D=190, V=2.5 => E9=271.346 kW
    approx(theoretical_power(2.5, 1.225, 190), 271.3458569404297, 1e-6)
    # C9=35.91, E9=271.346 => Cp=0.13234
    approx(power_coefficient(35.91, 2.5, 1.225, 190), 0.13234032907266224, 1e-9)
    # H9 = C9*(G9+1) = 35.91*(0.01+1) = 36.269
    approx(35.91 * (0.01 + 1), 36.269099999999995, 1e-9)
