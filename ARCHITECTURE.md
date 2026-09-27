# WindAnaly 软件架构文档

> 更新：2026-09-27 · 本轮重组（去 WindVault、目录提升、更新器换代）后的新基线
> 路线图见 [REFACTOR_PLAN.md](REFACTOR_PLAN.md)

## 1. 项目概览

**WindAnaly** 是测风塔数据风资源分析软件（对标 Windographer 工作流），
PySide6 + pandas/numpy 单机桌面应用。原双软件架构（WindVault 数据管理 +
WindRefine 数据分析）已收敛为单一软件；台账库（`data/windkit.db`）能力
内化为「文件 → Import/Export from Database」。

| 顶层 | 职责 |
|---|---|
| `windanaly.py` | 唯一入口（更新交接 + QApplication 装配 + 全局样式/字体） |
| `app.py` | AnalysisApp 主窗口：菜单/工具栏/8 Tab/动作分发/项目 IO |
| `core/` | 纯计算与数据层，**无 UI 依赖**（numpy/pandas/stdlib） |
| `ui/` | 控件与对话框（modules=8 Tab 与绘图引擎，dialogs=34 个对话框） |
| `updater/` | 独立更新器 updater.exe 源码（与主程序进程解耦） |
| `tests/` | 50 项 pytest 回归（core 算法层） |
| `data/` | 用户数据：settings.json / turbines.json / windkit.db（更新永不覆盖） |

## 2. 目录结构

```
WindAnaly/
├── windanaly.py            # 入口：python windanaly.py（冻结后 = WindAnaly.exe）
├── app.py                  # AnalysisApp 主窗口（UpdateMixin + QMainWindow）
├── build.py                # PyInstaller：主程序 onedir + updater.exe
├── core/                   # 18 文件 5,978 行
│   ├── dataset.py          #   Dataset/Channel/Flag 数据模型
│   ├── project.py          #   Project 会话 + .windanaly/.windrefine 持久化
│   ├── library.py          #   SQLite 台账库 CRUD（data/windkit.db）
│   ├── db_transfer.py      #   数据集 ↔ 台账库 导入/导出
│   ├── io_import.py        #   异构格式导入引擎（NRG/通用/雷达，1702 行）
│   ├── i18n.py             #   翻译系统（en→zh 正查 + zh→en 反查，903 词条）
│   ├── settings.py         #   JSON 设置持久化 + 自启动注册表
│   ├── version.py          #   VERSION / APP_NAME 唯一定义
│   ├── iec.py wind_rose.py diurnal.py histogram.py extreme_wind.py
│   ├── turbine_power.py wind_power.py table_stats.py
│   └── mcp_algorithms.py calculated_columns.py
├── ui/
│   ├── update_tools.py     #   UpdateMixin：拉起 updater.exe + 状态栏提示
│   ├── fallback_bar.py     #   自绘菜单栏/工具栏（多行换行）
│   ├── toolbar_icons.py    #   QPainter 彩色工具栏图标
│   ├── theme.qss
│   ├── modules/            # 8 个分析 Tab + PlotCanvas 自绘引擎（10 文件）
│   │   ├── plot.py         #   PlotCanvas：line/bar/hist/scatter/polar/table…（2639 行）
│   │   ├── analysis_tabs.py wind_rose_widget.py diurnal_widget.py
│   │   ├── histogram_widget.py scatter_widget.py tables_widget.py
│   │   ├── report_builder.py docx_writer.py
│   │   └── views.py        #   CDF/箱线/DMap/数据覆盖/文档历史/台账库链接
│   └── dialogs/            # 34 个功能对话框（10 文件）
│       ├── analysis_dialogs.py   # Analyze 菜单 16 个
│       ├── revise_dialogs.py     # Revise 菜单 7 个
│       ├── flag_dialogs.py       # Flag 菜单 8 个
│       ├── compare_dialogs.py    # Compare（含 MCP）
│       ├── tools_dialogs.py configure_dataset.py export_dialog.py
│       ├── calibration.py rose_properties.py language_settings.py
├── updater/                # 独立更新器（打包 updater.exe；tkinter，纯标准库）
│   ├── updater_main.py     #   界面/下载/安装/备份/恢复/自替换
│   ├── feed.py             #   多源版本索引（versions.json / GitHub / UNC）
│   ├── config.py           #   sources.json 加载 + app_dir
│   ├── version.py          #   版本比较
│   ├── sources.json        #   更新源配置（发版前可改）
│   └── updater.spec build_updater.bat
└── data/  tests/
```

## 3. 核心数据流

```
原始数据文件 → core.io_import.parse_file() → ParsedData
    → Dataset(df + channels + flags + calibrations)
        ├── library.store_series() → SQLite series_<id>（台账库）
        └── Project.datasets[] → .windanaly 会话（source + 通道分类 + 标记）
AnalysisApp ──set_project()──▶ 8 Tab（各 Tab 取 ds.df → core/*.py → PlotCanvas）
```

## 4. 自动更新（与 WindVault_QT 同机制）

- 主程序启动 → `ui.update_tools.UpdateMixin` 后台拉起 `updater.exe` 静默查询；
  发现新版写 `.update/available.json` → 状态栏提示（不弹窗）；
- 「帮助 → 检查更新」→ 前台拉起 updater.exe：多版本选择、全量包/增量链、
  sha256 校验、关主程序、`data/` 自动备份（pre_update_*.zip）、替换、重启、
  从备份恢复；updater.exe 可独立双击运行（主程序损坏自救）；
- 更新源 `updater/sources.json` 可配 GitHub Releases / HTTP / UNC，无需改代码。

## 5. 8 Tab 与对话框功能清单

| Tab | 核心 | 对话框菜单 |
|---|---|---|
| Summary / Time Series / Wind Rose / Diurnal / Histogram / Scatter / Data Table / Report | 切变、玫瑰 8×4、Weibull MLE、TI/IEC、25 种统计表、HTML/DOCX 报告 | Analyze×16 · Revise×7 · Flag×8 · Compare×2 · Tools×9 · Export 10 格式 |

（算法明细与缺口清单见 REFACTOR_PLAN.md §2 P7）

## 6. 开发与打包

```
python windanaly.py          # 开发运行
python -m pytest tests -q    # 回归（50 项）
python build.py              # 打包主程序 + 更新器 → dist/WindAnaly/
python build.py --updater    # 只重建更新器
```

版本号只改 `core/version.py`；发版 SOP 见 REFACTOR_PLAN.md §4.3。
