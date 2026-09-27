"""Reports 标签页的报告内容构建（HTML 预览 / PDF / DOCX 共用数据模型）。

ReportModel 从 Dataset 提取统计，输出统一的内容块序列：
  ('h1'|'h2'|'p', text) / ('table', rows) / ('image', png_bytes, w, h)
HTML 预览与 PDF 使用 HTML 渲染，DOCX 由 docx_writer 消费同一模型。
"""
import os
import tempfile

import numpy as np
import pandas as pd

from core import table_stats as ts
from core.histogram import weibull_fit_mle
from core.wind_power import wind_power_class
from core.wind_rose import compute_rose

_R_AIR = 287.05


class ReportModel:
    """从 Dataset 收集报告内容块。"""

    def __init__(self, ds, sections: list[str] | None = None,
                 title: str = 'Wind Resource Analysis Report'):
        self.ds = ds
        self.title = title
        self.sections = sections or ['summary', 'monthly', 'annual',
                                     'rose_img', 'monthly_img', 'weibull',
                                     'recovery']

    # ---- 数据工具 ----
    def _mean_of_kind(self, kind: str):
        for n, ch in self.ds.channels.items():
            if ch.kind == kind and n in self.ds.df.columns:
                v = pd.to_numeric(self.ds.df[n], errors='coerce')
                if v.notna().any():
                    return float(v.mean())
        return None

    def _speed_columns(self):
        return [(n, ch.height) for n, ch in self.ds.channels.items()
                if ch.kind == 'speed' and getattr(ch, 'role', 'Avg') == 'Avg'
                and n in self.ds.df.columns]

    def _air_density(self):
        temp = pres = None
        for n, ch in self.ds.channels.items():
            if ch.kind == 'temp' and temp is None and n in self.ds.df.columns:
                temp = n
            if ch.kind == 'pres' and pres is None and n in self.ds.df.columns:
                pres = n
        if not temp or not pres:
            return None
        t = pd.to_numeric(self.ds.df[temp], errors='coerce').mean()
        p = pd.to_numeric(self.ds.df[pres], errors='coerce').mean()
        if pd.isna(t) or pd.isna(p):
            return None
        return (p * 100.0) / (_R_AIR * (t + 273.15))

    def _power_density(self, height: float, rho: float | None):
        rho = rho or 1.225
        speeds = self._speed_columns()
        if not speeds:
            return None
        h, name = min(speeds, key=lambda t: abs((t[0] or 0) - height))
        v = pd.to_numeric(self.ds.df[name], errors='coerce').dropna()
        if v.empty:
            return None
        return float(0.5 * rho * (v ** 3).mean()), name

    # ---- 内容块 ----
    def blocks(self) -> list[tuple]:
        blocks: list[tuple] = [
            ('h1', self.title),
            ('p', f'Data set: {self.ds.name}'),
        ]
        df = self.ds.df
        blocks.append(('h2', '1. Data Set Summary'))
        rows = [['Data set', self.ds.name]]
        if len(df.index):
            rows.append(['Start date', str(pd.Timestamp(df.index[0]))])
            rows.append(['End date', str(pd.Timestamp(df.index[-1]))])
        rows.append(['Time steps', f'{len(df):,}'])
        if 'summary' in self.sections:
            attrs = getattr(self.ds, 'attrs', {})
            if attrs.get('lat') is not None:
                hemi = 'N' if float(attrs['lat']) >= 0 else 'S'
                rows.append(['Latitude',
                             f'{hemi} {abs(float(attrs["lat"])):.6f}'])
            if attrs.get('lon') is not None:
                hemi = 'E' if float(attrs['lon']) >= 0 else 'W'
                rows.append(['Longitude',
                             f'{hemi} {abs(float(attrs["lon"])):.6f}'])
            if attrs.get('elevation') is not None:
                rows.append(['Elevation', f'{float(attrs["elevation"]):g} m'])
            temp = self._mean_of_kind('temp')
            pres = self._mean_of_kind('pres')
            if temp is not None:
                rows.append(['Mean temperature', f'{temp:.1f} ℃'])
            if pres is not None:
                rows.append(['Mean pressure', f'{pres / 10.0:.1f} kPa'])
            rho = self._air_density()
            if rho is not None:
                rows.append(['Mean air density', f'{rho:.3f} kg/m3'])
            speeds = self._speed_columns()
            if rho is not None and speeds:
                name, h = min(speeds, key=lambda t: abs((t[1] or 0) - 50))
                v = pd.to_numeric(df[name], errors='coerce').dropna()
                if not v.empty:
                    wpd = 0.5 * rho * float((v ** 3).mean())
                    rows.append([f'Power density at {h:g}m',
                                 f'{wpd:.0f} W/m2'])
                    rows.append(['Wind power class',
                                 wind_power_class(wpd)])
        blocks.append(('table', rows))

        if 'weibull' in self.sections:
            speeds = self._speed_columns()
            if speeds:
                name, h = max(speeds, key=lambda t: t[1] or 0)
                v = pd.to_numeric(df[name], errors='coerce').dropna()
                fit = weibull_fit_mle(v.to_numpy())
                if fit:
                    k, c = fit
                    blocks.append(('h2', '2. Wind Speed Distribution'))
                    blocks.append(('p',
                                   f'Best-fit Weibull (MLE) of {name}: '
                                   f'k = {k:.2f}, c = {c:.2f} m/s, '
                                   f'mean = {v.mean():.2f} m/s'))

        if 'monthly' in self.sections:
            speeds = self._speed_columns()
            if speeds:
                name = speeds[-1][0]
                v = pd.to_numeric(df[name], errors='coerce').dropna()
                frame = ts.by_month_stats(df, name, with_all=True)
                rows = [['Month', 'Occurrences', 'Mean', 'Min', 'Max',
                         'Std. Dev.']]
                for m, r in frame.iterrows():
                    rows.append([str(m), f'{int(r["count"]):,}',
                                 f'{r["mean"]:.2f}' if pd.notna(r['mean']) else '',
                                 f'{r["min"]:.2f}' if pd.notna(r['min']) else '',
                                 f'{r["max"]:.2f}' if pd.notna(r['max']) else '',
                                 f'{r["std"]:.2f}' if pd.notna(r['std']) else ''])
                blocks.append(('h2', '3. Monthly Statistics '
                               f'({name})'))
                blocks.append(('table', rows))

        if 'annual' in self.sections:
            speeds = self._speed_columns()
            if speeds:
                name = speeds[-1][0]
                v = pd.to_numeric(df[name], errors='coerce').dropna()
                frame = ts.by_year_stats(df, name, with_all=True)
                rows = [['Year', 'Occurrences', 'Mean', 'Min', 'Max',
                         'Std. Dev.']]
                for y, r in frame.iterrows():
                    rows.append([str(y), f'{int(r["count"]):,}',
                                 f'{r["mean"]:.2f}' if pd.notna(r['mean']) else '',
                                 f'{r["min"]:.2f}' if pd.notna(r['min']) else '',
                                 f'{r["max"]:.2f}' if pd.notna(r['max']) else '',
                                 f'{r["std"]:.2f}' if pd.notna(r['std']) else ''])
                blocks.append(('h2', '4. Annual Statistics '
                               f'({name})'))
                blocks.append(('table', rows))

        if 'recovery' in self.sections:
            rows = [['Label', 'Valid Points', 'Recovery Rate (%)']]
            possible = len(df)
            for name in self.ds.channels:
                if name not in df.columns:
                    continue
                s = pd.to_numeric(df[name], errors='coerce')
                valid = int(s.notna().sum())
                rate = valid / possible * 100.0 if possible else 0.0
                rows.append([name, f'{valid:,}', f'{rate:.2f}'])
            blocks.append(('h2', '5. Data Recovery'))
            blocks.append(('table', rows))

        # 图片块由 ReportsTab 注入（风向玫瑰 / 月均值），依赖 UI
        return blocks


def blocks_to_html(blocks: list[tuple], image_dir: str | None = None) -> str:
    """内容块 → HTML（PDF/预览用；图片以文件路径引用）。"""
    out = ['<html><body style="font-family:Segoe UI,Arial;">']
    img_i = 0
    for b in blocks:
        kind = b[0]
        if kind == 'h1':
            out.append(f'<h1>{b[1]}</h1>')
        elif kind == 'h2':
            out.append(f'<h2>{b[1]}</h2>')
        elif kind == 'p':
            out.append(f'<p>{b[1]}</p>')
        elif kind == 'table':
            rows = b[1]
            out.append('<table border="1" cellspacing="0" cellpadding="3" '
                       'style="border-collapse:collapse;font-size:10pt;">')
            for r_i, row in enumerate(rows):
                tag = 'th' if r_i == 0 else 'td'
                out.append('<tr>' + ''.join(
                    f'<{tag}>{v}</{tag}>' for v in row) + '</tr>')
            out.append('</table><br>')
        elif kind == 'image' and image_dir:
            img_i += 1
            fn = f'report_img_{img_i}.png'
            with open(os.path.join(image_dir, fn), 'wb') as f:
                f.write(b[1])
            w = min(b[2], 620)
            out.append(f'<img src="{fn}" width="{w}"><br>')
    out.append('</body></html>')
    return '\n'.join(out)
