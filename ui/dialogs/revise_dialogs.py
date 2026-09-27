"""兼容 shim：实现已拆分至 ui/dialogs/revise/（S2），导入路径保持不变。"""
from ui.dialogs.revise.apply_scale_offset import ApplyScaleOffsetDialog
from ui.dialogs.revise.apply_time_shift import ApplyTimeShiftDialog
from ui.dialogs.revise.delete_data import DeleteDataDialog
from ui.dialogs.revise.fill_gaps import CoverageTimeline, FillGapsDialog
from ui.dialogs.revise.fix_quantization import FixQuantizationDialog
from ui.dialogs.revise.combine_sensors import CombineSensorsDialog
from ui.dialogs.revise.vertical_extrapolation import VerticalExtrapolationDialog, fill_1d, fill_2d, read_col, read_mat

__all__ = ['ApplyScaleOffsetDialog', 'ApplyTimeShiftDialog', 'DeleteDataDialog', 'FillGapsDialog', 'FixQuantizationDialog', 'CombineSensorsDialog', 'VerticalExtrapolationDialog']
