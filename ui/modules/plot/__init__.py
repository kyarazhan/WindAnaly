"""PlotCanvas 自绘绘图引擎（B4 拆分：门面 + 绘制/交互/导出 Mixin）。"""
# 兼容再导出：历史导入路径 ui.modules.plot（原单文件模块）保持不变
from ui.modules.plot._common import (CMAPS, PALETTE, _EPOCH_ORDINAL,
                                    _coerce_x_axis, _decimate_xy)
from ui.modules.plot.canvas import PlotCanvas
from ui.modules.plot.export_image import ExportImageDialog
from ui.modules.plot.properties import PlotPropertiesDialog

__all__ = ['PlotCanvas', 'PlotPropertiesDialog', 'ExportImageDialog',
           'PALETTE', 'CMAPS', '_EPOCH_ORDINAL']
