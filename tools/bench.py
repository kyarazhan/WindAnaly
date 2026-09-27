"""性能基准（S3-1）：1 年 10min × 30 通道合成数据，实测关键路径耗时。

用法: python tools/bench.py        （结果同时写入 outputs/bench_report.txt）
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pandas as pd


def build_csv(path: str) -> str:
    """1 年 10min × 30 通道（10 层风速+SD、10 层风向、温度、气压…）。"""
    idx = pd.date_range('2025-01-01', periods=365 * 144, freq='10min')
    n = len(idx)
    rng = np.random.default_rng(42)
    cols = {}
    for h in range(30, 220, 20):            # 10 层
        base = 6 + h * 0.012
        cols[f'WS{h}_Avg'] = np.abs(rng.normal(base, 3.0, n))
        cols[f'WS{h}_SD'] = np.abs(rng.normal(0.9, 0.2, n))
        cols[f'WD{h}_Avg'] = (rng.normal(210, 90, n)) % 360
    cols['Temp_Avg'] = 15 + 12 * np.sin(2 * np.pi * idx.dayofyear / 365)
    cols['Pres_Avg'] = 1013 + rng.normal(0, 8, n)
    cols['RH_Avg'] = np.clip(rng.normal(65, 20, n), 0, 100)
    df = pd.DataFrame(cols, index=idx)
    df.to_csv(path, encoding='utf-8')
    return f'{len(df)} 行 × {len(df.columns)} 列'


def main():
    results = []
    tmp = os.path.join(ROOT, 'outputs')
    os.makedirs(tmp, exist_ok=True)
    csv = os.path.join(tmp, 'bench_1y.csv')

    from core import io_import
    from core.dataset import Channel, Dataset

    if not os.path.exists(csv):
        t0 = time.perf_counter()
        desc = build_csv(csv)
        results.append(('生成基准数据', time.perf_counter() - t0, desc))

    t0 = time.perf_counter()
    parsed = io_import.parse_file(csv)
    dt = time.perf_counter() - t0
    results.append(('parse_file 导入', dt,
                    f'{len(parsed.df)} 行 / {len(parsed.channels)} 通道'))

    # 载入 Dataset（含通道注册/标记初始化）
    t0 = time.perf_counter()
    ds = Dataset('bench')
    ds.df = parsed.df
    ds.flags = pd.Series(False, index=parsed.df.index)
    ds.channels = {
        c['name']: Channel(c['name'], c['kind'], c.get('height'),
                           c.get('units', ''), c.get('role', ''))
        for c in parsed.channels}
    results.append(('Dataset 装配', time.perf_counter() - t0, ''))

    # 统计聚合（Tables 标签页的核心路径）
    from core import table_stats
    t0 = time.perf_counter()
    table_stats.monthly_means(ds.df, ds.channels) if hasattr(
        table_stats, 'monthly_means') else None
    dt = time.perf_counter() - t0
    results.append(('table_stats 月度聚合', dt, ''))

    # GUI：主窗口 + Time Series Tab 重绘（LOD 抽稀路径）
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from app import AnalysisApp
    t0 = time.perf_counter()
    win = AnalysisApp()
    win.show()
    app.processEvents()
    results.append(('主窗口构建', time.perf_counter() - t0, ''))

    win.project.add_dataset(ds)
    win._update_selection(ds)
    t0 = time.perf_counter()
    win._refresh_tabs()
    app.processEvents()
    results.append(('8 Tab 全量刷新(含绘图)', time.perf_counter() - t0, ''))

    win.close()

    lines = ['WindAnaly 性能基准（1 年 10min × 30 通道）', '=' * 46]
    for name, dt, note in results:
        lines.append(f'{name:28s} {dt * 1000:9.0f} ms  {note}')
    ok = all(dt < 1.5 for name, dt, _ in results
             if '导入' in name or '刷新' in name or '聚合' in name)
    lines.append('')
    lines.append('目标（导入/刷新/聚合 < 1.5s）：' + ('达标' if ok else '未达标'))
    report = '\n'.join(lines)
    print(report)
    with open(os.path.join(tmp, 'bench_report.txt'), 'w',
              encoding='utf-8') as f:
        f.write(report + '\n')


if __name__ == '__main__':
    main()
