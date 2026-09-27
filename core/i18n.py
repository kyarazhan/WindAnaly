"""WindAnaly 界面翻译（英文为底座，中文为翻译）。

所有界面字符串以英文为 key；settings['language'] == 'zh' 时从
settings['translations'] 读取对应中文。settings['english_corrections']
用于保存英文修正文案；展示英文时优先使用修正列（若已填写），
否则使用英文底座。

反向词典：历史代码中直接硬编码的中文文案，经 tr() 包裹后——
  · 中文模式：原样返回（行为与包裹前完全一致）；
  · 英文模式：从 REVERSE_TRANSLATIONS 取英文；缺失时仍返回中文
    （与旧行为一致，可逐步补全）。
"""

from core import settings

# 中文硬编码文案 → 英文（反向词典）。只收录界面可见文案。
REVERSE_TRANSLATIONS = {
    # 通用
    '全选': 'Select all',
    '取消': 'Cancel',
    '确定': 'OK',
    '关闭': 'Close',
    '保存': 'Save',
    '帮助': 'Help',
    '提示': 'Note',
    '操作': 'Action',
    '对象': 'Target',
    '时间': 'Time',
    '详情': 'Detail',
    '无': 'None',
    '无数据': 'No data',
    '颜色': 'Color',
    '单位': 'Units',
    '高度(m)': 'Height (m)',
    '均值': 'Mean',
    '最大': 'Max',
    '最小': 'Min',
    '月': 'Month',
    '年': 'Year',
    '从': 'from',
    '至': 'to',
    '启用': 'Enabled',
    '类别': 'Type',
    '类型': 'Type',
    '次类型': 'Subtype',
    '标准化标签': 'Standardized Label',
    '原始标签': 'Original Label',
    '检查更新': 'Check for Updates',
    '下载并安装': 'Download and Install',

    # Summary 摘要面板
    '数据集属性': 'Data Set Properties',
    '环境条件': 'Environmental Conditions',
    '风速与功率': 'Wind Speed & Power',
    '风切变系数': 'Wind Shear Coefficients',
    '纬度': 'Latitude',
    '经度': 'Longitude',
    '海拔': 'Elevation',
    '起始日期': 'Start Date',
    '结束日期': 'End Date',
    '持续时长': 'Duration',
    '时间步长': 'Time Step',
    '数据点数': 'Data Points',
    '静风阈值': 'Calm Threshold',
    '平均气温': 'Mean Air Temperature',
    '平均气压': 'Mean Air Pressure',
    '平均空气密度': 'Mean Air Density',
    '空气密度比': 'Air Density Ratio',
    '平均风速': 'Mean Wind Speed',
    '平均风速 @ ': 'Mean Wind Speed @ ',
    '功率密度': 'Power Density',
    '风功率等级': 'Wind Power Class',
    '参考高度范围': 'Reference Height Range',
    '风切变指数 α': 'Power Law Exponent α',
    '拟合优度 R²': 'Goodness of Fit R²',
    '地表粗糙度': 'Surface Roughness',
    '粗糙度等级': 'Roughness Class',
    '有效高度层数': 'Valid Height Levels',
    '分钟': 'minutes',
    '天': 'days',

    # 图表标题 / 轴标签
    '垂直风切变廓线': 'Vertical Wind Shear Profile',
    '月平均风速': 'Monthly Mean Wind Speed',
    '日变化风速廓线': 'Diurnal Wind Speed Profile',
    '风向玫瑰图': 'Wind Direction Frequency',
    '通道数据有效率': 'Data Recovery by Channel',
    '累积分布函数': 'Cumulative Distribution Function',
    '累积分布函数 (CDF)': 'Cumulative Distribution Function (CDF)',
    '平均风速 (m/s)': 'Mean Wind Speed (m/s)',
    '离地高度 (m)': 'Height (m)',
    '月份': 'Month',
    '小时': 'Hour of Day',
    '风玫瑰计算异常': 'Wind rose calculation error',
    '风玫瑰图属性': 'Wind Rose Properties',

    # 视图窗口
    '数据覆盖': 'Data Coverage',
    '文档历史': 'Document History',
    '数据的载入、保存、剔除与关闭等操作会记录在此，随项目文件持久化。':
        'Loading, saving, filtering and closing of data are recorded here '
        'and persisted with the project file.',
    '色块越绿表示该通道在对应时段的有效率越高；灰色为该时段全缺测。':
        'Greener cells mean higher data recovery in that period; grey means '
        'no data at all.',
    '从测风塔台账数据库中选择数据集链接到本分析。':
        'Link a data set from the mast ledger database to this analysis.',
    '链接所选数据集': 'Link Selected Data Set',
    '链接台账数据库': 'Link Database',
    '（台账库中暂无数据集）': '(No data sets in the ledger database yet)',
    '请先载入数据集': 'No data set loaded',
    '请勾选至少一条有效通道': 'Select at least one valid channel',
    '请选择有效的数据集': 'Please select a valid data set',
    '通道（勾选绘制）：': 'Channels (check to plot):',

    # 空态 / 计算提示
    '未载入数据集': 'No data set loaded',
    '请选择数据列': 'Select a data column',
    '请选择第二数据列': 'Select a second data column',
    '数据列不可用': 'Data column unavailable',
    '无有效数据点': 'No valid data points',
    '无有效数据': 'No valid data',
    '无有效比值': 'No valid ratios',
    '无风速通道': 'No wind speed channels',
    '无风向通道': 'No wind direction channels',
    '无风向数据': 'No wind direction data',
    '风速层数不足': 'Not enough wind speed levels',
    '至少需要两层风速': 'At least two wind speed levels required',
    '至少需要两层风向': 'At least two wind direction levels required',
    '至少需要两层温度': 'At least two temperature levels required',
    '需要至少两个高度的风速传感器': 'Wind speed sensors at two or more '
        'heights are required',
    '无法识别高度': 'Cannot identify height',
    '无法从列名识别高度': 'Cannot identify height from column name',
    '未选择系列': 'No series selected',
    '计算失败': 'Calculation failed',
    'PDF 计算失败': 'PDF calculation failed',
    '日变化计算失败': 'Diurnal calculation failed',
    '月统计计算失败': 'Monthly statistics calculation failed',
    '无月度数据': 'No monthly data',
    '缺少配对的 SD 通道，无法计算 TI': 'No paired SD channel; TI unavailable',
    '请选择风速传感器': 'Select a wind speed sensor',
    '请选择温度传感器': 'Select a temperature sensor',
    '请选择传感器对与风向': 'Select a sensor pair and direction sensor',
    '请选择分子/分母风速': 'Select numerator/denominator wind speeds',
    '请选择风速对': 'Select a wind speed pair',
    '请选择真值与预测列': 'Select truth and prediction columns',

    # Revise 对话框
    '应用比例与偏移': 'Apply Scale and Offset',
    '修改范围': 'Modify',
    '修改全部时间步': 'all time steps',
    '修改指定时间段': 'only the interval:',
    '数值变换': 'Value Transform',
    '删除数据': 'Delete Data',
    '删除所选列': 'Delete selected columns',
    '删除所选列中的数据点': 'Delete data points in selected columns',
    '无视标记状态': 'regardless of flags',
    '仅删除被标记为...的数据点': 'only data points flagged as...',
    '仅删除未被标记为...的数据点': 'only data points NOT flagged as...',
    '标记过滤：': 'Flag filter: ',
    '组合风速仪': 'Combine Sensors',
    '垂直外推': 'Vertical Extrapolation',
    '未选择': 'No selection',
    '未选择标记': 'No flag selected',
    '未勾选': 'Not checked',
    '无匹配': 'No match',
    '没有符合条件的数据点': 'No data points match the criteria',
    '无通道': 'No channels',
    '通道不足': 'Not enough channels',
    '通道重复': 'Duplicate channels',
    '通道重名': 'Duplicate name',
    '两个通道不能相同': 'The two channels must differ',
    '请勾选要删除的通道': 'Check the columns to delete',
    '请至少勾选一个数值通道': 'Check at least one numeric channel',
    '请选择至少一个标记': 'Select at least one flag',
    '请选择两个风速通道': 'Select two wind speed channels',
    '请至少指定一个源高度和一个目标高度': 'Specify at least one source height '
        'and one target height',
    '请勾选 Wind speed': 'Check a Wind speed column',
    '请勾选 Wind direction': 'Check a Wind direction column',
    '请勾选 Temperature': 'Check a Temperature column',
    '参数不足': 'Missing parameters',
    '重名': 'Duplicate name',
    '已删除 ': 'Deleted ',
    '已从 ': 'Deleted from ',
    '已对 ': 'Applied to ',
    '已组合 ': 'Combined ',
    '已生成外推通道': 'Extrapolated channels generated',
    ' 个通道': ' columns',
    ' 个通道删除 ': ' columns, deleted ',
    ' 个通道应用 Offset=': ' columns, Offset=',
    ' 个时间点': ' data points',
    '」已存在': '" already exists',

    # 温度/风速/风向组合名（垂直外推标签）
    '温度 (Temperature)': 'Temperature',
    '风速 (Speed)': 'Wind speed',
    '风向 (Direction)': 'Wind direction',

    # Configure Data Set
    '配置数据集': 'Configure Data Set',
    '数据列属性': 'Column Properties',

    # Compare
    '请先选择 Target 与 Reference 数据集。': 'Select both a Target and a '
        'Reference data set.',
    'Target 与 Reference 均需包含风速通道。': 'Both Target and Reference must '
        'contain wind speed channels.',
    '两个数据集在所选时间步下重叠样本不足，无法估算偏移。': 'Not enough '
        'overlapping samples at the selected time step to estimate the offset.',
    '未能从该文件识别到可用的时序数据。': 'No usable time series data could '
        'be recognized in that file.',
    '生成的数据集为空。': 'The generated data set is empty.',
    '从文件导入数据集': 'Import a data set from a file',
    '导出失败': 'Export failed',
    '加载失败': 'Load failed',
    '请选择至少一列': 'Select at least one column',

    # 语言设置
    'Language Settings / 语言设置': 'Language Settings',
    '界面语言 / Language：': 'Language: ',
    '中文': 'Chinese',
    '中文翻译 / Chinese': 'Chinese Translation',
    '英文修正 / English Correction': 'English Correction',
    '英文底座 / English Base': 'English Base',
    '展示英文修正列 / Use English corrections': 'Use English corrections',
    '恢复默认中文 / Restore Default Chinese': 'Restore Default Chinese',
    '取消 / Cancel': 'Cancel',
    '确定 / OK': 'OK',

    # 更新对话框
    '正在检查更新…': 'Checking for updates...',
    '正在下载…': 'Downloading...',
    '发现新版本可用。': 'A new version is available.',
    '发现新版本（强制更新）。': 'A new version is available (forced update).',
    '已是最新版本。': 'You are up to date.',
    '最新版本：未知': 'Latest version: unknown',
    '未能获取更新信息（网络不可达或所有更新源暂不可用）。':
        'Could not fetch update information (network unreachable or no '
        'update source available).',

    # 日期方位等
    '东': 'E',
    '南': 'S',
    '西': 'W',
    '北': 'N',
    '东北': 'NE',
    '东南': 'SE',
    '西北': 'NW',
    '西南': 'SW',
    '标准差': 'Std. dev.',
    '气温': 'Temperature',
    '气压': 'Pressure',
    '相对湿度': 'Relative Humidity',
    '垂直风速': 'Vertical Wind Speed',
    '筛选条件': 'Filter criteria',
    '日期范围': 'Date range',
    '该日期范围无数据': 'No data in this date range',

    # ------------------------------------------------------------------
    # 通用界面词条
    '文件': 'File',
    '预览': 'Preview',
    '工具': 'Tools',
    '设置': 'Settings',
    '设置…': 'Settings...',
    '联系作者': 'Contact Author',
    '软件说明': 'About',
    '数据导入…': 'Import Data...',
    '数据导出…': 'Export Data...',
    '删除站点…': 'Delete Station...',
    '新增站点…': 'Add Station...',
    '编辑站点…': 'Edit Station...',
    '异常处理': 'Quality Control',
    '异常处理 · 序列号 {}': 'Quality Control · Serial {}',
    '查看站点数据概况': 'Station Data Overview',
    '站点数据概况 · 序列号 {}': 'Station Data Overview · Serial {}',
    '就绪 · 数据管理': 'Ready · Data Management',
    '删除确认': 'Delete Confirmation',
    '确定删除站点「{}」（序列号 {}）及其全部数据集？\n此操作不可撤销。':
        'Delete station "{}" (serial {}) and all its data sets?\n'
        'This cannot be undone.',
    '已删除站点：序列号 {}': 'Station deleted: serial {}',
    '请先在台账中选择一个站点': 'Select a station in the ledger first',
    '请先在台账中选择一条记录': 'Select a record in the ledger first',
    '该站点无已导入的数据集': 'No imported data sets for this station',

    # 站点对话框
    '新增站点': 'Add Station',
    '编辑站点': 'Edit Station',
    '站点号': 'Station No.',
    '位置': 'Location',
    '设备类型': 'Device Type',
    '开始日期': 'Start Date',
    '纬度': 'Latitude',
    '经度': 'Longitude',
    '海拔(m)': 'Elevation (m)',

    # 导入对话框
    '数据导入 · 标准化确认': 'Data Import · Standardization Review',
    '浏览…': 'Browse...',
    '未选择文件': 'No file selected',
    '请先选择并解析数据文件': 'Select and parse a data file first',
    '解析失败': 'Parse failed',
    '解析文件时出错：\n{}': 'Error parsing file:\n{}',
    '已导入：{}\n{} 行 · {} 通道': 'Imported: {}\n{} rows · {} channels',
    '已导入：序列号 {} · {} · 模式={}': 'Imported: serial {} · {} · mode={}',
    '库内（数据整体入库 windkit.db）':
        'In database (all data stored in windkit.db)',
    '外链（保留原始文件，库只登记路径）':
        'External link (keep original file; ledger stores the path only)',
    '默认库内（数据整体入库 windkit.db）':
        'Default in-database (all data stored in windkit.db)',
    '默认外链（原始文件留原处，库只登记）':
        'Default external link (keep original file in place)',
    '标准化确认：核对每个通道的规范名（可编辑）；取消勾选「有效」的通道将不入库。':
        'Standardization review: check each standardized name (editable); '
        'channels unchecked as "Valid" will not be imported.',
    '确认并导入': 'Review & Import',
    '原始列名': 'Original Column',
    '标准化名(可改)': 'Standardized (editable)',
    '后缀': 'Suffix',
    '规范名重复：{}': 'Duplicate name: {}',
    '标准化名重复：{}': 'Duplicate name: {}',
    '⚠ 该站点号已存在于台账，将作为不同序列号分别记录':
        '⚠ This station number already exists; it will be recorded as a '
        'separate serial number',

    # 标准化对话框
    '数据标准化 · 系统设定': 'Data Standardization · System Rules',
    '数据标准化 · 序列号 {}': 'Data Standardization · Serial {}',
    '  标准化是系统级设定：所有导入数据统一按以下规则命名存储。\n  标准化名 = 类型 高度m [方位] 统计\u3000例：SPEED 10m AVG':
        '  Standardization is a system-level setting: all imported data is '
        'named and stored by the rules below.\n  Standardized name = TYPE '
        'heightm [orient] STAT, e.g. SPEED 10m AVG',
    '  在台账选中站点后打开本对话框，可对该站数据逐通道执行标准化（含有效性确认）。':
        '  Open this dialog with a station selected in the ledger to '
        'standardize its channels one by one (with validity review).',
    '  该站点无可用时序数据（外部文件缺失或库内为空）':
        '  No time series data for this station (external file missing or '
        'database empty)',
    '该站点无可用时序数据（外部文件缺失或库内为空）':
        'No time series data for this station (external file missing or '
        'database empty)',
    '  逐通道标准化：核对规范名（可编辑）；取消「有效」勾选的通道将被剔除。「执行标准化」后统一写回数据库。':
        '  Channel-by-channel standardization: review the standardized '
        'names (editable); channels unchecked as "Valid" will be dropped. '
        '"Apply Standardization" writes everything back to the database.',
    '规范 Base': 'Base',
    '统计（导入时逐通道确认）': 'Statistics (confirmed per channel on import)',
    '执行标准化': 'Apply Standardization',
    '导出 CSV': 'Export CSV',
    '导出 WRA 格式': 'Export WRA Format',
    '标准化': 'Standardization',
    '标准化完成': 'Standardization Complete',
    '无改动（名称与有效性均未变化）。': 'No changes (names and validity '
        'unchanged).',
    '已导出': 'Exported',
    '已导出：{}': 'Exported: {}',
    '有效✔': 'Valid',
    '有效率%': 'Recovery %',
    '最大值': 'Max',
    '最小值': 'Min',
    '平均值': 'Mean',
    '数值': 'Value',
    '时段': 'Period',
    '通道': 'Channel',
    '统计': 'Statistic',
    '最大/最小': 'Max/Min',
    '偏差σ': 'SD σ',

    # 编辑通道
    '编辑通道 · 序列号 {}': 'Edit Channels · Serial {}',
    '该站点无数据集（先导入数据）': 'No data set for this station (import '
        'data first)',
    '按规则重算标准化名': 'Recalculate Standardized Names',
    '名称为空': 'Empty name',
    '第 {} 行标准化名为空': 'Standardized name in row {} is empty',
    '已保存': 'Saved',
    '通道注册已更新（{} 个改名已同步时序）。':
        'Channel registry updated ({} renames synced to the time series).',
    '标高(m)': 'Height (m)',
    '方位': 'Orient',

    # 质控对话框
    '该站点无可用时序数据（外部文件缺失或库内为空）（外部文件缺失或库内为空）':
        'No time series data for this station',
    '范围检验（风速/风向/温度/气压 超出区间即异常）':
        'Range test (speed/direction/temperature/pressure out of range)',
    '风速区间 [m/s]': 'Speed range [m/s]',
    '风向区间 [°]': 'Direction range [°]',
    '温度区间 [℃]': 'Temperature range [°C]',
    '气压区间 [hPa]': 'Pressure range [hPa]',
    '停滞检验（风速滚动标准差过小 → 冻结）':
        'Stagnation test (rolling std of speed too small → frozen)',
    '停滞窗口(点)': 'Stagnation window (points)',
    '停滞 σ 阈值': 'Stagnation σ threshold',
    '风向突变（相邻风向差超过阈值）':
        'Direction jump (adjacent difference over threshold)',
    '突变阈值 [°]': 'Jump threshold [°]',
    '恒值/死传感器（通道方差过小 → 失效）':
        'Constant/dead sensor (channel variance too small → failed)',
    '方差阈值': 'Variance threshold',
    '勾选规则并调整范围后，点击「应用并统计」预览结果。':
        'Pick rules and adjust ranges, then click "Apply & Statistics" to '
        'preview.',
    '应用并统计': 'Apply & Statistics',
    '导出筛选后 CSV': 'Export Filtered CSV',
    '请至少选择一条筛选规则。': 'Select at least one QC rule.',
    '请先「应用并统计」生成过滤结果':
        'Click "Apply & Statistics" first to generate filtered results',
    '行': 'rows',
    ' 行': ' rows',

    # 设置对话框
    '常规': 'General',
    '开机自启动（写入当前用户启动项）':
        'Launch at startup (writes to current user startup entries)',
    '启动后后台静默检查更新': 'Silently check for updates in background',
    '记住并恢复窗口尺寸': 'Remember and restore window size',
    '数据存储': 'Data Storage',
    '数据库位置': 'Database Location',
    '打开位置': 'Open Location',
    '界面': 'Interface',
    '字体大小': 'Font Size',
    '修改后点击「确定」保存并立即生效。':
        'Click "OK" after changing to save and apply immediately.',
    '自启动': 'Auto-start',
    '未能写入启动项（当前平台不支持或权限不足），其余设置已保存。':
        'Could not write startup entries (unsupported platform or no '
        'permission); other settings were saved.',

    # 预览 / 关于
    '未找到该序列号对应的台账记录': 'No ledger record for this serial number',
    '（该站点尚无已导入的数据集）': '(No imported data sets for this station)',
    '\u3000\u3000位置：': '  Location: ',
    '\u3000\u3000时间范围：': '  Period: ',
    '\n设备类型：': '\nDevice type: ',
    '\n完整率：': '\nCompleteness: ',
    '%\u3000\u3000数据集数：': '%  Data sets: ',

    # 项目内动态消息（f-string 模板）
    '已写出 {} 行 / {} 列至：\n{}': 'Written {} rows / {} columns to:\n{}',
    '已写出 {} 行至：\n{}': 'Written {} rows to:\n{}',
    '当前版本：v{}': 'Current version: v{}',
    '最新版本：v{}': 'Latest version: v{}',
    '\n（重启 WindAnaly 后生效）': '\n(Takes effect after restarting WindAnaly)',
    ' · 序列号 ': ' · Serial ',
    ' · 模式=': ' · mode=',
    ' 行标准化名为空': ' standardized names empty',
    ' 个改名已同步时序）。': ' renames synced to time series).',
    ' 个无效通道剔除': ' invalid channels dropped',
    ' 个通道改名': ' channels renamed',
    ' 行 / ': ' rows / ',
    ' 行至：\n': ' rows to:\n',
    ' 列至：\n': ' columns to:\n',
    '输出通道「{}」已存在': 'Output channel "{}" already exists',
    '数据读取失败：{}': 'Failed to read data: {}',
    ' · 库内': ' · in-database',
    '已新增站点：序列号 {}': 'Station added: serial {}',
    '已更新站点：序列号 {}': 'Station updated: serial {}',
    '修改「类型/标高/方位/统计」后点「按规则重算标准化名」自动生成；同类型同高度多支传感器自动加后缀 A/B/C…（后缀下拉可直接输入其它字母）。也可直接改「标准化名」。保存将同步数据集通道注册与时序列名。':
        'After changing Type/Height/Orient/Statistics, click "Recalculate '
        'Standardized Names" to auto-generate. Multiple sensors of the same '
        'type at the same height get suffixes A/B/C... (type any other '
        'letter in the suffix combo). You can also edit the standardized '
        'name directly. Saving syncs the channel registry and the time '
        'series columns.',
    '标准化名': 'Standardized Name',
    '累积概率': 'Cumulative Probability',
    '当前图表没有可导出的数据。': 'The current chart has no data to export.',
    '序列号': 'Serial No.',
    '坐标': 'Coordinates',
    '完整率(%)': 'Recovery (%)',
    '时间范围': 'Period',

}

# 英文底座 -> 中文翻译。这是界面的默认中文显示。
DEFAULT_TRANSLATIONS = {
    # 主窗口
    'WindAnaly · Data Analysis': 'WindAnaly · 数据分析',

    # 顶部菜单
    '&File': '文件(F)',
    '&View': '视图(V)',
    '&Revise': '修正(R)',
    '&Flag': '标记(F)',
    '&Analyze': '分析(A)',
    '&Compare': '对比(C)',
    '&Tools': '工具(T)',
    '&Settings': '设置(S)',
    '&Window': '窗口(W)',
    '&Help': '帮助(H)',

    # 文件
    '&New...': '新建(N)...',
    '&Open...': '打开(O)...',
    'Link Database...': '链接数据库...',
    'Open Folder...': '打开文件夹...',
    '&Add...': '增加(A)...',
    'Add Directory...': '增加目录...',
    '&Close': '关闭(C)',
    '&Save': '保存(S)',
    'Save &As...': '另存为...',
    '&Export Data...': '导出数据...',
    'Import from Database...': '从数据库导入...',
    'Export to Database...': '导出到数据库...',
    'Recent Files': '最近文件',
    'E&xit': '退出(X)',

    # 视图
    'Home Tabs': '首页展示',
    'Data Coverage...': '数据覆盖...',
    'Document History...': '文档历史...',
    'DMap...': 'DMap...',
    'Boxplot...': '箱线图...',
    'CDF...': '累积分布函数...',
    'Toolbar': '工具栏',
    'Status Bar': '状态栏',

    # 修正
    'Configure Data Set...': '配置数据集...',
    'Calibration...': '校准...',
    'Apply Scale and Offset...': '应用比例与偏移...',
    'Apply Time Shift...': '应用时移...',
    'Delete Data...': '删除数据...',
    'Fill Missing Values...': '填补缺失值...',
    'Fill Gaps...': '填补缺失值...',
    'Repair Quantization...': '修复量化...',
    'Fix Quantization...': '修复量化...',
    'Combine Sensors...': '组合风速仪...',
    'Combine Anemometers...': '组合风速仪...',
    'Vertical Extrapolation...': '垂直外推...',

    # 标记
    'Manual Flag...': '手动标记...',
    'Flag by Scatter...': '按散点图标记...',
    'Flag by Rule...': '按规则标记...',
    'Flag Tower Shadow...': '标记塔影...',
    'Check and Remove Flags...': '检查并移除标记...',
    'Clear All Flags': '清除全部标记',
    'Flag Statistics': '查看剔除统计',
    'Define Flags...': '定义标记...',
    'Define Common Flags...': '定义常用标记...',
    'View Common Flag Rules...': '查看常用标记规则...',

    # 分析
    'Data Recovery...': '数据恢复...',
    'Turbulence...': '湍流...',
    'Wind Shear...': '风切变...',
    'Wind Speed Distribution...': '风速分布...',
    'Speed Ratio...': '风速比...',
    'Tower Shadow Distortion...': '塔影畸变...',
    'Temperature Profile...': '温度廓线...',
    'Turbine Output...': '风机出力...',
    'Inflow Angle...': '入流角...',
    'Wind Power Class...': '风功率等级...',
    'Short Time Interval...': '短时间间隔...',
    'Long-term Analysis...': '长期分析...',
    'Exceedance Probability...': '超越概率...',
    'Extreme Wind Speed...': '极端风速...',
    'Representative Year...': '代表年...',
    'Prediction Error...': '预测误差...',

    # 对比
    'Compare Data Sets...': '对比数据集...',
    'Measure-Correlate-Predict (MCP)...': '测量-相关-预测（MCP）...',

    # 工具
    'Customize Toolbar...': '自定义工具栏...',
    'Check for Updates': '检查更新',

    # 设置
    'Language...': '语言设置...',

    # 窗口
    'New Window': '新建窗口',
    'Cascade': '层叠',
    'Tile': '平铺',
    'Close All Windows': '关闭所有窗口',

    # 帮助
    'Contents...': '目录...',
    'Index...': '索引...',
    'License Management...': '许可管理...',
    'License Agreement...': '许可协议...',
    'Project Homepage...': '访问项目主页...',
    'Version History...': '查看版本历史...',
    'Demo Videos...': '查看演示视频...',
    'About WindAnaly': '关于 WindAnaly',

    # Tab 名称
    'Summary': '汇总',
    'Time Series': '时间序列',
    'Wind Rose': '风玫瑰',
    'Diurnal Profile': '日变化廓线',
    'Histogram': '频率分布',
    'Scatter Plot': '散点图',
    'Data Table': '数据表',
    'Report': '报告',

    # 工具栏自定义对话框
    'Customize Toolbar': '自定义工具栏',
    'WindAnaly Toolbar': 'WindAnaly 快捷工具栏',

    # ---- 新控件通用标签（2026-09-03 i18n 补全）----
    'Data column': '数据列',
    'Display': '显示',
    'Format': '格式',
    'Filter by': '筛选条件',
    'Flag': '标记',
    'Include': '包含',
    '<Unflagged data>': '<未标记数据>',
    'Date': '日期',
    'Year': '年',
    'Month': '月',
    'Date range': '日期范围',
    'Direction sector': '风向扇区',
    'Sectors': '扇区数',
    'Direction sensor': '风向传感器',
    'Width': '宽度',
    'Start at': '起始值',
    'Make first bin half this width': '首箱半宽',
    'Chart': '图表',
    'Table': '表格',
    'Help': '帮助',
    'Settings': '设置',
    'Results': '结果',
    'Export Table...': '导出表格...',
    'Copy Selection': '复制选中',
    'Copy Table': '复制表格',
    'Copy Table Transposed': '复制转置表格',
    'Export Table Transposed...': '导出转置表格...',
    'Export PDF...': '导出 PDF...',
    'Export DOCX...': '导出 DOCX...',
    'Refresh Preview': '刷新预览',
    'Report title': '报告标题',
    'Sections': '章节',
    'Create Report': '生成报告',
    'About WindAnaly': '关于 WindAnaly',

    # Histogram
    'Frequency': '频率',
    'Occurrences': '频次',
    'one data column': '单数据列',
    'data column and month': '数据列与月份',
    'data column and hour of day': '数据列与小时',
    'two data columns': '双数据列',
    'Primary bins': '主分箱',

    # Scatter
    'Plot': '绘图列',
    'versus': '对比列',
    'Color code by': '颜色编码',
    'Show line of best fit': '显示最佳拟合线',
    'Number of': '数量',
    'Mean x value': 'X 均值',
    'Mean y value': 'Y 均值',

    # Diurnal
    'Single profile': '单廓线',
    'By month': '按月',
    'Use only time steps containing data for all selected columns':
        '仅使用所有选定列均有数据的时间步',

    # Extreme Wind
    'Wind speed sensor': '风速传感器',
    'Mode': '模式',
    'Mean wind speeds': '平均风速',
    'Gusts': '阵风',
    'Period': '周期',
    'Min recovery (%)': '最小恢复率(%)',
    'Periodic Maxima': '周期最大值法',
    'Method of Independent Storms': '独立风暴法',
    'Threshold (m/s)': '阈值(m/s)',
    'Set Recommended': '设为推荐值',
    'Independence (hours)': '独立性(小时)',
    '50-yr extreme (m/s)': '50年极值(m/s)',
    'EWTS II (Exact)': 'EWTS II (精确)',
    'EWTS II (Gumbel)': 'EWTS II (Gumbel)',
    'EWTS II (Davenport)': 'EWTS II (Davenport)',

    # Long Term
    'Annual means': '年均值',
    'Histogram of Annual Means': '年均值直方图',
    'Frequency Rose by Year': '逐年频率玫瑰',
    'Monthly Profile by Year': '逐年月轮廓',
    'Diurnal Profile by Year': '逐年日轮廓',
    'Frequency Histogram by Year': '逐年频率直方图',
    'Inter-Annual Variation': '年际变率',

    # Tables
    'Bin column': '分箱列',
    'Combine years together': '合并年份',

    # ------------------------------------------------------------------
    # 图表属性 / 导出图像（plot.py）
    'Properties': '属性',
    'Properties...': '属性...',
    'Title': '标题',
    'X axis label': 'X 轴标签',
    'Y axis label': 'Y 轴标签',
    'Y2 axis label': 'Y2 轴标签',
    'Fix min/max': '固定最小/最大值',
    'Units': '单位',
    'Label': '标签',
    'Color': '颜色',
    'Fonts': '字体',
    'Font size': '字号',
    'Line width': '线宽',
    'Logarithmic': '对数刻度',
    'Fix minimum': '固定最小值',
    'Fix maximum': '固定最大值',
    'Gridlines at major division': '主刻度网格线',
    'Gridlines at minor division': '次刻度网格线',
    'Specify font sizes by entering sizes directly:': '直接输入字号：',
    'Export Image': '导出图像',
    'Export Image...': '导出图像...',
    'Image dimensions': '图像尺寸',
    'Use actual plot dimensions': '使用实际绘图尺寸',
    'x-axis': 'X 轴',
    'y-axis': 'Y 轴',
    'Include axis labels': '包含轴标签',
    'plot title': '绘图标题',
    'legend': '图例',
    'Transparent background (for metafiles only)': '透明背景（仅图元文件）',
    'Image preview': '图像预览',
    'Export type': '导出类型',
    'Copy Bitmap': '复制位图',
    'Copy': '复制',
    'Axes': '坐标轴',
    'Channels': '通道',

    # 导出数据（export_dialog.py）
    'Export Data': '导出数据',
    'Export Data...': '导出数据...',
    'Export...': '导出...',
    'Export': '导出',
    'Icing': '结冰',
    'Invalid': '无效',
    'all time steps': '全部时间步',
    'only the interval:': '仅指定区间：',
    'from': '从',
    'Preview settings': '预览设置',
    'Automatically update preview': '自动更新预览',
    'Update Preview': '更新预览',
    'Select data columns to export': '选择要导出的数据列',
    'Select all': '全选',
    'Data': '数据',
    'Export date and time': '导出日期和时间',
    'minutes': '分钟',
    'Other settings': '其他设置',
    'Custom:': '自定义：',
    'Maintain constant wind speed': '保持恒定风速',
    'First bin half this size': '首区间取此宽度一半',
    'frequencies': '频率',
    'occurrences': '次数',
    'Remove seasonal bias': '去除季节偏差',
    'Scale to mean wind speed of': '缩放至平均风速',
    'Offset directions clockwise': '风向顺时针偏移',
    'Property': '属性',
    'Time steps in time series': '时间序列中的时间步数',
    'WAsP options': 'WAsP 选项',
    'WindSim options': 'WindSim 选项',
    'Meteodyn WT options': 'Meteodyn WT 选项',
    'Openwind options': 'Openwind 选项',
    'single height': '单高度',
    'multiple heights': '多高度',
    'has a mean speed of': '平均风速为',
    'Scale speeds so': '缩放风速使',
    'Properties of exported data': '导出数据属性',
    'WindFarmer options': 'WindFarmer 选项',
    'EPE options': 'EPE 选项',
    'MGM options': 'MGM 选项',
    'XML Metadata': 'XML 元数据',
    'This file describes the data set and its data columns, but contains no time series data.': '此文件描述数据集及其数据列，但不包含时间序列数据。',
    'File preview': '文件预览',

    # 日变化 / 散点图 / 其他通用
    'Clear All': '全部清除',
    'frequency': '频率',
    'flag': '标记',
    'data column': '数据列',
    'Mean x value :': 'X 均值：',
    'Mean y value :': 'Y 均值：',
    'Direction sector:': '方向扇区：',
    'Data column': '数据列',
    'Change Color Scheme': '更改配色方案',
    'Help': '帮助',
    'Close': '关闭',
    'Boxplot': '箱线图',

    # 第二轮补充（短词与模板串）
    'All': '全部',
    'Min': '最小',
    'Max': '最大',
    'End': '结束',
    'End:': '结束：',
    'End time': '结束时间',
    'End date': '结束日期',
    'Min.': '最小',
    'Max.': '最大',
    'Maximum': '最大值',
    'Minute': '分钟',
    'Min. value:': '最小值：',
    'Max. value:': '最大值：',
    'Max. wind speed': '最大风速',
    'All wind speed': '全部风速',
    'All wind direction': '全部风向',
    'All temperature': '全部温度',
    'All pressure': '全部气压',
    'All humidity': '全部湿度',
    'All other': '全部其他',
    'All bins': '全部区间',
    'Minimum number of time steps': '最少时间步数',
    'Min recovery (%)': '最小恢复率 (%)',
    'Maximum likelihood': '极大似然',
    'Minimum data coverage rate': '最低数据覆盖率',
    'Maximum height of vertical wind shear profile graph':
        '风切变廓线图的最大高度',
    'Auto-associate SD/Max/Min': '自动关联标准差/最大/最小列',
    'Date/Time component': '日期/时间分量',
    'Poly coefficients (c0,c1,...)': '多项式系数 (c0,c1,...)',
    'Overall R2: 0.751': '总体 R2：0.751',
    'Direction sectors: 1': '方向扇区数：1',
    'Yearly divisions: 1': '年度分区数：1',
    'Direction sectors:': '方向扇区数：',
    'Sector 1 center:': '扇区 1 中心：',
    'Sector 2 center:': '扇区 2 中心：',
    'Number of points selected: 0': '已选点数：0',
    'You have selected 0 flagged segments': '您已选择 0 个被标记的区段',
    'WindSim 4.8 and earlier': 'WindSim 4.8 及更早版本',
    'WindSim 4.9 and later': 'WindSim 4.9 及更新版本',
    'Preferred edition of IEC standard 61400-1 for':
        'IEC 61400-1 标准首选版本（用于',
    'To export multiple heights the data set must contain speed, TI, direction, and temperature columns at each height. Use the Vertical Extrapolation window to generate one or more such columns.':
        '要导出多高度数据，数据集必须包含每个高度的风速、湍流强度、风向和温度列。请使用垂直外推窗口生成一列或多列此类数据。',
    'You must select at least one measurement height to export an MM2 file.':
        '导出 MM2 文件必须至少选择一个测量高度。',

    # 数据库导出
    'No active data set. Open a data set first.': '无活动数据集。请先打开一个数据集。',
    'Exported to database: serial {} · {} · {} columns':
        '已导出到数据库：序列号 {} · {} · {} 列',
    'Exported to database:\nSerial {} · {}\n{} columns stored.':
        '已导出到数据库：\n序列号 {} · {}\n已存储 {} 列数据。',

    # 填补缺失值（Fill Gaps，对齐原版对话框）
    'Fill Gaps': '填补缺失值',
    'Fill Gaps...': '填补缺失值...',
    'Start time': '开始时间',
    'Synthesized': '合成数据',
    'Low quality': '低质量',
    'Tower shading': '塔影',
    'What action should Windographer perform?': '请选择要执行的操作：',
    'Reconstruct using data from other heights where available':
        '优先使用其它高度的可用数据进行重建',
    'Reconstruct, then fill remaining gaps with synthetic data':
        '重建后，再用合成数据填补剩余缺测',
    'Fill gaps in': '填补范围',
    'particular time segment': '指定时间段',
    'Flag gap filled segments with': '为填补的段落设置标记：',
    'Fill gaps in the following data columns:': '填补以下数据列的缺失：',
    'Statistic': '统计项',
    'Entire Data Set': '整个数据集',
    'Selected Subset': '所选子集',
    'Total data points': '数据点总数',
    'Missing data points': '缺测数据点',
    'Data completeness (%)': '数据完整率 (%)',
    'Number of gaps': '缺测段数',
    'Mean gap length (hr)': '平均段长 (h)',
    'Shortest gap (hr)': '最短段长 (h)',
    'Longest gap (hr)': '最长段长 (h)',
    'No columns': '未选择列',
    'Please select at least one data column': '请至少选择一个数据列',
    'Filled {} data points in {} columns': '已填补 {} 列中 {} 个数据点',

    # 修复量化（Fix Quantization，对齐原版）
    'Fix Quantization': '修复量化',
    'Fix Quantization...': '修复量化...',
    'Original Data': '原始数据',
    'Modified Data': '修改后数据',
    'Frequency Density': '频率密度',
    'original': '原始',
    'modified': '修改后',
    'from': '从',
    'to': '到',
    'No data': '无数据',
    'Quantization fixed: {} (step {})': '已修复量化：{}（步长 {}）',
    'Your data is highly quantized. This operation will have a significant effect on your data.':
        '数据存在高度量化。此操作将对数据产生显著影响。',
    'Your data shows moderate quantization. This operation may have a moderate effect on your data.':
        '数据存在中等程度量化。此操作可能对数据产生中等影响。',
    'Your data is not very highly quantized. Using this window will likely not have a significant effect on your data.':
        '数据的量化程度不高。使用此窗口预计不会对数据产生明显影响。',

    # 标准化命名（Configure Data Set / 编辑通道 / 导入确认）
    'Suffix': '后缀',
    'Recalculate Standardized Names': '按规则重算标准化名',
    'Rebuild standardized labels as "SPEED 120m W AVG"; multiple sensors at the same height and type get suffixes A, B, C...':
        '按"类型 高度m 方位 统计"规则重算标准化标签（如 SPEED 120m W AVG）；同类型同高度的多支传感器自动加后缀 A、B、C…',
    'Subtype': '次类型',
    'Height': '高度',
    'Type': '类型',
    'Flag Manually': '手动标记',
    'Time interval:': '时间区间：',
    'Start:': '开始：',
    'End:': '结束：',
    'Data columns:': '数据列：',
    'Update this list when I select a segment': '选中数据段时自动更新此列表',
    'Flag to apply or remove:': '要应用/移除的标记：',
    'Apply Flag to Segment': '对数据段应用标记',
    'Remove Flag from Segment': '从数据段移除标记',
    'Remove All Flags from Segment': '清除数据段的全部标记',
    'Table Settings...': '表格设置...',
    'All wind speed columns': '全部风速列',
    'All wind direction columns': '全部风向列',
    'Copy Selection': '复制所选',
    'Choose visible data columns by': '可见数据列选择方式',
    'data column types': '按数据列类型',
    'data column names': '按数据列名称',
    'Data column type': '数据列类型',
    'Color code cells according to data column type': '按数据列类型着色单元格',
    'Shorten labels longer than': '标签超过此长度时截断：',
    'characters': '个字符',
    'Wind speed': '风速',
    'Vertical wind speed': '垂直风速',
    'Wind direction': '风向',
    'Temperature': '温度',
    'Air pressure': '气压',
    'Relative humidity': '相对湿度',
    'Mean': '均值',
    'Start Time': '开始时间',

    # Vertical Extrapolation（原版布局）
    'Vertical Extrapolation': '垂直外推',
    'Synthesize:': '合成：',
    'for these heights:': '目标高度：',
    'Flag new columns with': '为新列设置标记',
    'Power law exponent': '幂律指数',
    'Calculate in each time step': '在每个时间步计算',
    'Specify as a constant': '指定为常数',
    'Specify by month': '按月指定',
    'Specify by hour of day': '按小时指定',
    'Specify by direction sector': '按方向扇区指定',
    'Specify by month and hour of day': '按月和小时指定',
    'Specify by direction sector and month': '按方向扇区和月指定',
    'Specify by direction sector and hour of day': '按方向扇区和小时指定',
    'Calculate from': '计算源',
    'Calculate from:': '计算源：',
    'Extrapolate from': '外推源',
    'Enter constant power law exponent': '输入常数幂律指数',
    'Constant power law exponent': '常数幂律指数',
    'Enter power law exponent by month': '按月输入幂律指数',
    'Enter power law exponent by hour of day': '按小时输入幂律指数',
    'Enter power law exponent by direction sector': '按方向扇区输入幂律指数',
    'Enter power law exponent by month and hour of day': '按月和小时输入幂律指数',
    'Enter power law exponent by direction sector and month': '按方向扇区和月输入幂律指数',
    'Enter power law exponent by hour of day and direction sector': '按小时和方向扇区输入幂律指数',
    'Direction sensor': '风向传感器',
    'Direction sectors': '方向扇区数',
    'Restrict power law exponent to a range': '将幂律指数限制在范围内',
    'Min. value': '最小值',
    'Max. value': '最大值',
    'Month': '月份',
    'Hour': '小时',
    'Direction Sector': '方向扇区',
    'Power Law': '幂律',
    'Power Law Exponent': '幂律指数',
    'Lapse rate (°C/100 m)': '温度直减率 (°C/100 m)',
    'Synthesize Data & Append To Data Set...': '合成数据并追加到数据集...',
    'Wind direction is assumed uniform with height; the synthesized columns copy the reference direction channel.':
        '风向假定随高度不变：合成列直接复制参考风向通道。',
    'Select a time interval, check the data columns, then click Apply Flag to Segment. Select rows in the table to choose a segment; the chart highlights it in yellow.':
        '先设定时间区间并勾选数据列，再点击"对数据段应用标记"。在表格中选中行即为选段，图表会以黄色高亮显示。',
    'Select at least one checkbox': '请至少勾选一项',

    # Direction Tab（风向切变率）
    'Wind veer rate': '风向切变率',
    'Restrict wind veer rate to a range': '将风向切变率限制在范围内',
    'Min. value (\u2191100m)': '最小值 (\u2191100m)',
    'Max. value (\u2191100m)': '最大值 (\u2191100m)',
    'Enter constant wind veer rate': '输入常数风向切变率',
    'Constant wind veer rate (\u2191100m)': '常数风向切变率 (\u2191100m)',
    'Enter wind veer rate by month': '按月输入风向切变率',
    'Enter wind veer rate by hour of day': '按小时输入风向切变率',
    'Enter wind veer rate by direction sector': '按方向扇区输入风向切变率',
    'Enter wind veer rate by month and hour of day': '按月和小时输入风向切变率',
    'Wind Veer': '风向切变',
    'Rate (\u2191100m)': '切变率 (\u2191100m)',

    # Temperature Tab（温度梯度）
    'Temperature gradient': '温度梯度',
    'Restrict temperature gradient to a range': '将温度梯度限制在范围内',
    'Enter constant temperature gradient': '输入常数温度梯度',
    'Constant temperature gradient (°C/100m)': '常数温度梯度 (°C/100m)',
    'Enter temperature gradient by month': '按月输入温度梯度',
    'Enter temperature gradient by hour of day': '按小时输入温度梯度',
    'Enter temperature gradient by direction sector': '按方向扇区输入温度梯度',
    'Enter temperature gradient by month and hour of day': '按月和小时输入温度梯度',
    'Enter temperature gradient by direction sector and month': '按方向扇区和月输入温度梯度',
    'Enter temperature gradient by hour of day and direction sector': '按小时和方向扇区输入温度梯度',
    'Gradient (°C/100m)': '梯度 (°C/100m)',

}

# 旧版中文 base -> 英文底座的映射，用于 settings 迁移。
_OLD_ZH_TO_EN = {
    'WindAnaly · 数据分析': 'WindAnaly · Data Analysis',
    '文件(F)': '&File',
    '视图(V)': '&View',
    '修正(R)': '&Revise',
    '标记(F)': '&Flags',
    '分析(A)': '&Analysis',
    '对比(C)': '&Compare',
    '工具(T)': '&Tools',
    '设置(S)': '&Settings',
    '窗口(W)': '&Window',
    '帮助(H)': '&Help',
    '新建(N)...': '&New...',
    '打开(O)...': '&Open...',
    '链接数据库...': 'Link Database...',
    '打开文件夹...': 'Open Folder...',
    '增加(A)...': '&Add...',
    '增加目录...': 'Add Directory...',
    '关闭(C)': '&Close',
    '保存(S)': '&Save',
    '另存为...': 'Save &As...',
    '导出数据...': '&Export Data...',
    '从数据库导入...': 'Import from Database...',
    '导出到数据库...': 'Export to Database...',
    '最近文件': 'Recent Files',
    '退出(X)': 'E&xit',
    '首页展示': 'Home Tabs',
    '数据覆盖...': 'Data Coverage...',
    '文档历史...': 'Document History...',
    'DMap...': 'DMap...',
    '箱线图...': 'Boxplot...',
    '累积分布函数...': 'CDF...',
    '工具栏': 'Toolbar',
    '状态栏': 'Status Bar',
    '配置数据集...': 'Configure Data Set...',
    '校准...': 'Calibration...',
    '应用比例与偏移...': 'Apply Scale and Offset...',
    '应用时移...': 'Apply Time Shift...',
    '删除数据...': 'Delete Data...',
    '插补缺失值...': 'Fill Missing Values...',
    '修复量化...': 'Repair Quantization...',
    '组合风速仪...': 'Combine Sensors...',
    '垂直外推...': 'Vertical Extrapolation...',
    '手动标记...': 'Manual Flag...',
    '按散点图标记...': 'Flag by Scatter...',
    '按规则标记...': 'Flag by Rule...',
    '标记塔影...': 'Flag Tower Shadow...',
    '检查并移除标记...': 'Check and Remove Flags...',
    '清除全部标记': 'Clear All Flags',
    '查看剔除统计': 'Flag Statistics',
    '定义标记...': 'Define Flags...',
    '定义常用标记...': 'Define Common Flags...',
    '查看常用标记规则...': 'View Common Flag Rules...',
    '数据恢复...': 'Data Recovery...',
    '湍流...': 'Turbulence...',
    '风切变...': 'Wind Shear...',
    '风速分布...': 'Wind Speed Distribution...',
    '风速比...': 'Speed Ratio...',
    '塔影畸变...': 'Tower Shadow Distortion...',
    '温度廓线...': 'Temperature Profile...',
    '风机出力...': 'Turbine Output...',
    '入流角...': 'Inflow Angle...',
    '风功率等级...': 'Wind Power Class...',
    '短时间间隔...': 'Short Time Interval...',
    '长期分析...': 'Long-term Analysis...',
    '超越概率...': 'Exceedance Probability...',
    '极端风速...': 'Extreme Wind Speed...',
    '代表年...': 'Representative Year...',
    '预测误差...': 'Prediction Error...',
    '对比数据集...': 'Compare Data Sets...',
    '测量-相关-预测（MCP）...': 'Measure-Correlate-Predict (MCP)...',
    '自定义工具栏...': 'Customize Toolbar...',
    '检查更新': 'Check for Updates',
    '语言设置...': 'Language...',
    '中英文对照表...': 'Language...',
    '新建窗口': 'New Window',
    '层叠': 'Cascade',
    '平铺': 'Tile',
    '关闭所有窗口': 'Close All Windows',
    '目录...': 'Contents...',
    '索引...': 'Index...',
    '许可管理...': 'License Management...',
    '许可协议...': 'License Agreement...',
    '访问项目主页...': 'Project Homepage...',
    '查看版本历史...': 'Version History...',
    '查看演示视频...': 'Demo Videos...',
    '关于 WindAnaly': 'About WindAnaly',
    '汇总': 'Summary',
    '时间序列': 'Time Series',
    '风玫瑰': 'Wind Rose',
    '日变化': 'Diurnal Profile',
    '日变化廓线': 'Diurnal Profile',
    '频率分布': 'Histogram',
    '散点图': 'Scatter Plot',
    '数据表': 'Data Table',
    '报告': 'Report',
    '自定义工具栏': 'Customize Toolbar',
    'WindAnaly 快捷工具栏': 'WindAnaly Toolbar',
}


def _migrate_old_translations(old: dict) -> dict:
    """把旧版中文 key 的 translations 迁移为新版英文 key。"""
    new = {}
    for k, v in old.items():
        en = _OLD_ZH_TO_EN.get(k, k)
        new[en] = v
    return new


def ensure_defaults():
    """补全默认中文翻译；迁移旧 settings；补全默认英文修正（空）。"""
    trans = settings.get('translations', {})
    # 发现旧版中文 key 则迁移
    if trans and any(k in _OLD_ZH_TO_EN for k in trans):
        trans = _migrate_old_translations(trans)
        settings.set('translations', trans)
    changed = False
    for k, v in DEFAULT_TRANSLATIONS.items():
        if k not in trans:
            trans[k] = v
            changed = True
    if changed:
        settings.set('translations', trans)
    corrections = settings.get('english_corrections', {})
    corr_changed = False
    for k in DEFAULT_TRANSLATIONS:
        if k not in corrections:
            corrections[k] = ''
            corr_changed = True
    if corr_changed:
        settings.set('english_corrections', corrections)


def _has_cjk(s: str) -> bool:
    return any('\u4e00' <= ch <= '\u9fff' for ch in s)


def tr(en_text: str, *args) -> str:
    """取界面字符串。

    - language == 'zh'：返回英文底座对应的中文翻译；中文底座的串原样返回。
    - language == 'en'：英文底座返回 english_corrections 中的非空修正
      （否则原文）；中文底座（历史硬编码文案）从 REVERSE_TRANSLATIONS
      取英文，缺失时原样返回。
    支持 {} 占位格式化。
    """
    if not en_text:
        return ''
    if settings.get('language', 'zh') != 'en':
        trans = settings.get('translations', {})
        return trans.get(en_text, DEFAULT_TRANSLATIONS.get(en_text, en_text)).format(*args)
    if _has_cjk(en_text):
        # 中文底座（历史硬编码）→ 反向词典
        return REVERSE_TRANSLATIONS.get(en_text, en_text).format(*args)
    corrections = settings.get('english_corrections', {})
    corrected = corrections.get(en_text, '')
    if corrected:
        return corrected.format(*args)
    return en_text.format(*args)


def language() -> str:
    return settings.get('language', 'zh')


def switch(lang: str):
    settings.set('language', lang)


# ---------------------------------------------------------------------------
# 翻译对照表导出/导入（CSV，供用户在外部编辑后回传）
# ---------------------------------------------------------------------------
def export_translation_table(path: str):
    """导出完整翻译对照表到 CSV。

    列：英文底座 / 当前中文翻译 / 英文修正。
    用户编辑"当前中文翻译"或"英文修正"列后，可用 import_translation_table 导回。"""
    import csv
    trans = settings.get('translations', {})
    corr = settings.get('english_corrections', {})
    # 合并：DEFAULT_TRANSLATIONS + settings 翻译 + corrections 的 key
    all_keys = sorted(set(DEFAULT_TRANSLATIONS) | set(trans) | set(corr))
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['English (key)', 'Chinese (当前中文翻译)',
                    'English Correction (英文修正,可空)'])
        for k in all_keys:
            w.writerow([k, trans.get(k, DEFAULT_TRANSLATIONS.get(k, '')),
                        corr.get(k, '')])


def import_translation_table(path: str):
    """从 CSV 导入用户编辑后的翻译对照表并写入 settings。

    仅更新"Chinese"与"English Correction"两列；英文底座列作为 key 匹配。"""
    import csv
    trans = settings.get('translations', {})
    corr = settings.get('english_corrections', {})
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get('English (key)', '').strip()
            if not key:
                continue
            zh = row.get('Chinese (当前中文翻译)', '').strip()
            en_fix = row.get('English Correction (英文修正,可空)',
                             '').strip()
            if zh:
                trans[key] = zh
            if en_fix:
                corr[key] = en_fix
    settings.set('translations', trans)
    settings.set('english_corrections', corr)
