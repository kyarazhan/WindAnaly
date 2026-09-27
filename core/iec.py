"""IEC 61400-1 各版本湍流分类（WindAnaly 唯一事实源）。

依据 Windographer 4.0.28 帮助（11.2 Turbulence Analysis）与 IEC 标准：

- 2nd Ed (1999)：特征湍流强度 TI（P84 ≈ mean + 1σ），
  类别（基于 15 m/s 特征 TI）：B ≤ 0.16 / A ≤ 0.18 / S > 0.18
- 3rd Ed (2005)：平均湍流强度（对数正态），
  类别（基于 15 m/s 平均 TI）：C ≤ 0.12 / B ≤ 0.14 / A ≤ 0.16 / S > 0.16
- 4th Ed (2019)：TI 参考值（P70 第 70 百分位，Weibull 分布），
  新增 A+ 适应热带气旋/高湍流：
  C ≤ 0.12 / B ≤ 0.14 / A ≤ 0.16 / A+ ≤ 0.18 / S > 0.18
- 4.1 (AMD1:2025)：沿用 4th 的参考 TI 与类别，并新增
  NTM / NTM90、DEL 参考载荷、S1–S3 结构类、1 年/50 年极端风速回归期等。

本模块同时供“Analyze ▸ Turbulence Analysis”对话框按用户首选版本出分类。
（注：Workbench 的“湍流曲线”模块刻意对齐源 Excel「第二版」表，保持 2nd 固定，
不在此处联动，以免破坏与源表的对照契约。）
"""
from __future__ import annotations

import numpy as np

# 版本顺序（用于 UI 下拉与回退）
IEC_EDITION_ORDER = ['2nd', '3rd', '4th', '4.1']
IEC_EDITION_LABELS = {
    '2nd': '2nd edition (1999)',
    '3rd': '3rd edition (2005)',
    '4th': '4th edition (2019)',
    '4.1': '4.1 edition (AMD1:2025)',
}


def iec_ti_type(edition: str) -> str:
    """返回该版本用于类别判定的 TI 统计量类型。"""
    if edition == '2nd':
        return 'characteristic'   # P84 = mean + 1σ
    if edition == '3rd':
        return 'representative'   # P90 = mean + 1.28σ
    return 'reference'            # 4th / 4.1：P70 参考值（Weibull）


def iec_ti_label(edition: str) -> str:
    """结果表列头显示用 TI 类型标签。"""
    return {
        '2nd': 'Characteristic TI',
        '3rd': 'Representative TI',
        '4th': 'Reference TI',
        '4.1': 'Reference TI',
    }[edition]


def iec_edition_short(edition: str) -> str:
    """短标签，用于“IEC x ed.”列头。"""
    return edition


def iec_categories(edition: str) -> list[tuple[str, float | None]]:
    """从低湍流到高湍流返回 (类别, 上限阈值)；上限 None 表示无上界(S)。

    与 Windographer 帮助 11.2 的表格一致：
      - 2nd：B ≤ 0.16 / A ≤ 0.18 / S > 0.18
      - 3rd：C ≤ 0.12 / B ≤ 0.14 / A ≤ 0.16 / S > 0.16
      - 4th / 4.1：C ≤ 0.12 / B ≤ 0.14 / A ≤ 0.16 / A+ ≤ 0.18 / S > 0.18
    """
    if edition == '2nd':
        return [('B', 0.16), ('A', 0.18), ('S', None)]
    if edition == '3rd':
        return [('C', 0.12), ('B', 0.14), ('A', 0.16), ('S', None)]
    # 4th / 4.1：参考 TI 在 15 m/s，新增 A+
    return [('C', 0.12), ('B', 0.14), ('A', 0.16), ('A+', 0.18), ('S', None)]


def classify_ti(edition: str, ti_value: float) -> str:
    """按版本阈值将 TI 值归类为 IEC 湍流类别。"""
    if ti_value is None or (isinstance(ti_value, float) and np.isnan(ti_value)):
        return '-'
    for label, upper in iec_categories(edition):
        if upper is None or ti_value <= upper:
            return label
    return 'S'


def ti_value_for_classification(edition: str, ti_array) -> float:
    """对 15 m/s 区间的 TI 序列，按版本定义计算用于类别判定的 TI 值。

    - 2nd：P84 ≈ 均值 + 1σ（假定正态，与 Windographer 一致）
    - 3rd：P90（representative）
    - 4th / 4.1：P70（reference value）
    """
    a = np.asarray(ti_array, dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return float('nan')
    if edition == '2nd':
        return float(a.mean() + a.std(ddof=1))
    if edition == '3rd':
        return float(np.percentile(a, 90))
    return float(np.percentile(a, 70))  # 4th / 4.1
