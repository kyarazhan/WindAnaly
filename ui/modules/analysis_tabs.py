"""兼容 shim：实现已拆分至 ui/modules/tabs/（S2），导入路径保持不变。"""
from ui.modules.tabs.summary import SummaryTab
from ui.modules.tabs.time_series import TimeSeriesTab
from ui.modules.tabs.simple import WindRoseTab, DiurnalTab, HistogramTab, ScatterTab, TablesTab
from ui.modules.tabs.reports import ReportsTab
from ui.modules.tabs._common import (AnalysisTab, actual_name,
                                    display_name, ts_ordinals)

__all__ = ['AnalysisTab', 'SummaryTab', 'TimeSeriesTab',
           'WindRoseTab', 'DiurnalTab', 'HistogramTab',
           'ScatterTab', 'TablesTab', 'ReportsTab',
           'display_name', 'actual_name', 'ts_ordinals']
