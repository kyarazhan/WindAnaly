"""兼容 shim：实现已拆分至 ui/dialogs/analysis/（S2），导入路径保持不变。"""
from ui.dialogs.analysis.basic import DataRecoveryDialog, TurbulenceDialog, WindShearDialog, WindSpeedDistributionDialog, WindSpeedRatiosDialog, TowerDistortionDialog, TemperatureProfileDialog
from ui.dialogs.analysis.energy import WindTurbineOutputDialog, InflowAngleDialog, WindPowerClassDialog
from ui.dialogs.analysis.advanced import ShortTimeIntervalDialog, LongTermAnalysisDialog, ProbabilityOfExceedenceDialog, ExtremeWindAnalysisDialog, RepresentativeYearDialog, ForecastErrorAnalysisDialog

__all__ = ['DataRecoveryDialog', 'TurbulenceDialog', 'WindShearDialog', 'WindSpeedDistributionDialog', 'WindSpeedRatiosDialog', 'TowerDistortionDialog', 'TemperatureProfileDialog', 'WindTurbineOutputDialog', 'InflowAngleDialog', 'WindPowerClassDialog', 'ShortTimeIntervalDialog', 'LongTermAnalysisDialog', 'ProbabilityOfExceedenceDialog', 'ExtremeWindAnalysisDialog', 'RepresentativeYearDialog', 'ForecastErrorAnalysisDialog']
