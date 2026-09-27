# WindAnaly 重构、优化与迭代规划书

> 版本：v1.7 · 2026-09-27（v1.0.5 发布后更新）
> 基于对全量代码的审计（57 个 .py / 35,525 行）与本轮架构重组后的现状
> 配套文档：[ARCHITECTURE.md](ARCHITECTURE.md)（新架构说明）

---

## 0.8 v1.0.5 记录（2026-09-27）

- 修复用户报告：独立更新器安装完整包报「不是有效的更新包」——
  `extract_preserve_data` 安装前校验与 1.0.4 修的 `_pick_local_pkg` 同源
  （未剥离发布包顶层目录），现已统一走 `_zip_entries` 归一化；
  新增 4 项安装校验回归测试（真实 1.0.2 完整包端到端复现通过）。
- 增量包构成分析（1.0.4→1.0.5，6 文件 21.7MB）：app 层仅 2 个小 .pyc ✓，
  但 WindAnaly.exe（10MB）/updater.exe（11.65MB）/base_library.zip（1.33MB）
  因 PyInstaller 构建不可复现而每次进补丁。
  **下一步优化（S5 继续）**：构建缓存——对 exe/运行时的输入（桩 + 依赖
  清单哈希）做哈希，未变化时复用上一版产物，使补丁落到 app 层真实体积。

---

## 0.7 S5 第一步完成记录（2026-09-27，随 v1.0.4 发布）

| 项 | 结果 |
|---|---|
| 独立更新器修复 | ①本地包校验复用 `_zip_entries`，带顶层目录的完整包不再误判无效；②独立模式版本识别改读 `data/app_version.txt`（build 写入、release.py 随每个补丁强制注入），在线版本列表与增量链规划恢复正常 |
| S5 分发瘦身（第一步） | 模块化分发落地：`tools/boot_frozen.py` 引导桩（独立桩目录交给 PyInstaller，防业务码进 exe）+ `app/*.pyc` 业务层（77 个文件）+ `_internal/` 运行时；隐藏依赖由业务源码 AST 扫描自动生成；完整包 82.7→**61.9 MB** |
| 效果预期 | 本次补丁含一次性目录迁移（22.5 MB）；自 1.0.5 起日常补丁只含 app/*.pyc 变更，预期 KB~MB 级 |
| 已知噪声 | 运行时构建日志有 `feed`/`version` 两个 hidden-import 警告（updater 兄弟模块名，仅独立 exe 使用，无影响） |

**S5 剩余**：运行时哈希缓存（依赖不变时跳过运行时重建）；KB 级补丁实测；
性能热点向量化按需；多语言扩展按需。

---


## 0.6 S4 第一批完成记录（2026-09-27，随 v1.0.3 发布）

| S4 项 | 结果 |
|---|---|
| 发布自动化 | `tools/release.py <版本> --notes "说明"`：版本校验→build→exe 冒烟→完整包→**基线自动重演**（上一版全量包+其后的补丁）→sha256 diff 增量包→versions.json，全程一条龙；本版即由该工具实战产出 |
| 缺口清单复核 | 修正 §2 P7 与 S4 的过时信息：MCP 8 算法、11 种计算列、台账库导入导出**早已实现**（旧档继承的假缺口）；真实剩余 = ASC/ROW/NDF/RLD 专用解析器 |
| 发布目录 | 版本包统一放 `release/`（完整包/增量包/源码归档三件套 + `<版本>/versions.json` 索引），策略写入 RELEASE.md §0 |

**真实源验证**：索引合并 4 个版本；1.0.2→1.0.3 单跳、1.0.0→1.0.3 三跳链
规划全部正确；发布包 updater 正确发现 1.0.3。

---

## 0.3 S2 第一批完成记录（2026-09-27，随 v1.0.1 发布）

巨型文件拆分 6 个中已完成 4 个（全部「行为不变」，每步 run_checks 全绿）：

| 原文件 | 拆分结果 |
|---|---|
| `app.py`（2,008 → **875** 行） | `core/loader.py`（格式常量/merge_frames/scan_data_files 纯函数）+ `ui/app_menus.py`（MenusMixin：菜单/工具栏/重翻译）+ `ui/app_project.py`（ProjectIoMixin：项目文件+最近文件）+ `ui/app_loader.py`（LoaderMixin：装载/来源解析）；app.py 只留装配与动作分发 |
| `revise_dialogs.py`（2,692 → shim） | `ui/dialogs/revise/` 包：_common + 每对话框一文件（7 个）；原模块变纯 re-export shim，导入路径不变 |
| `analysis_dialogs.py`（1,964 → shim） | `ui/dialogs/analysis/` 包：_common + basic/energy/advanced 三组；shim 同上 |
| `analysis_tabs.py`（1,808 → shim） | `ui/modules/tabs/` 包：_common（基类+助手）+ summary/time_series/simple/reports；shim 同上 |

拆分方法约定（后续批次沿用）：行段机械搬移、Mixin/self 经 MRO 运行期解析、
共享助手进 `_common.py`、原模块保留为 re-export shim（外部导入零改动）、
每拆一个跑 compileall+pytest+GUI 冒烟。

**S2 剩余（第二批）**：`plot.py`（2,639，绘图引擎，风险最高单独立批）、
`export_dialog.py`（2,094，先评估 10 格式 writer 可分性）。

## 0.4 v1.0.1 发布记录（2026-09-27）

- S2 第一批重构随本版发布；按增量发布策略，Release 资产仅含
  `1.0.0-1.0.1-patch.zip` + `versions.json`（增量索引），不再上传全量包；
  新用户仍从 v1.0.0 全量包安装后增量升级。
- 索引归档：`release/1.0.0/versions.json`、`release/1.0.1/versions.json`。

## 0.5 S3 第一批完成记录（2026-09-27，随 v1.0.2 发布）

| S3 项 | 结果 |
|---|---|
| 更新器图标 | `updater/updater_icon.ico`（圆角蓝底+循环刷新箭头+风车心，多尺寸 16-256）；绘制工具 `tools/make_updater_icon.py` 可复跑；updater.spec 已接入 |
| S3-4 UI 冒烟入回归 | `tools/smoke_ui.run_smoke()` + `tests/test_smoke_ui.py`（offscreen）：主窗口+8 Tab+9 菜单+6 个主要对话框构造；pytest 总数 54→**65** |
| S3-2 项目格式 v3 | `PROJECT_FORMAT=3` + `migrate_payload` 迁移链（v1→v2→v3，未来版本明确报错）；payload 新增 `app_version` 溯源；6 项迁移测试 |
| S3-3 导入注册表化 | `io_import._PARSERS` + `register_parser`：专用解析器（Symphonie/Windographer/Molas/WRA）以 match 谓词注册，兜底链由注册表驱动；新格式零侵入接入；4 项测试 |
| S3-1 性能基准 | `tools/bench.py`（1 年 10min×33 通道）：导入 1.62s→**1.30s**、8 Tab 全量刷新 1.29s→**0.79s**，目标 <1.5s 达标。优化点：`_as_num` 免重复整列 to_numeric、`_find_time_col` 跳过纯数字列、`_read_lines_robust` 限量嗅探 |
| 发布物留存策略 | 本地 `release/archives/` 留存三件套（完整包/增量包/源码归档）；GitHub 只传增量包+versions.json（写入 RELEASE.md §0） |

**S3 剩余（第二批）**：真 py-spy 深度 profile、`.windanaly` 内嵌通道快照、
ASC/ROW/NDF/RLD 新格式解析器（注册表已就位，逐个补）。


---

## 0. 本轮已完成的重组（2026-09-27）

本轮完成「去 WindVault 化 + 目录提升 + 更新器换代 + 品牌统一」，作为后续
迭代的新基线：

| 事项 | 结果 |
|---|---|
| 移除 WindVault 子软件 | 删除 `windvault/`（11 文件）、启动器（`main.py`/`launch.py`）、`run_*.py` 双入口、`shared/ui/launcher.py` |
| 移除历史垃圾 | 删除 `_src/`（200+ 临时脚本）、`outputs/`（冒烟截图）、旧 `shared/updater/`（进程内旧更新机制） |
| 目录提升 | `windrefine/` 与 `shared/` 合并提升到根目录：`core/`（19 文件，纯计算+数据层）、`ui/`、`app.py`（主窗口） |
| 品牌统一 | WindRefine / WindKit / WindMatrix → **WindAnaly**（窗口标题、菜单、i18n 词条、导出文件头、注册表自启动键、关于对话框） |
| 项目文件 | 新项目存为 `.windanaly`；打开时兼容 `.windrefine`（不丢用户历史项目） |
| 更新器换代 | 移植 WindVault_QT 的**独立 updater.exe 机制**（详见 §4） |
| 入口统一 | 唯一入口 `windanaly.py`（开发 `python windanaly.py`，打包 `WindAnaly.exe`） |
| 验证 | pytest 全部通过；离屏 GUI 冒烟通过 |
| 回滚保障 | 重构前全量备份：`Project/WindAnaly_pre_refactor_20260927.zip`（21 MB） |

### 0.1 S1 批次完成记录（2026-09-27）

| S1 项 | 结果 |
|---|---|
| git 仓库化 | 本机无 git，采用便携版 Git；`.gitignore` 补充排除用户数据（`data/windkit.db`、`data/settings.json`、`data/backups/`）；远程 `github.com/kyarazhan/WindAnaly` |
| settings 键收敛 | `windrefine_*` → `analy_*`（toolbar/tabs_visible/recent_files），`core/settings.py` 内置幂等迁移：**文件里只有旧键时才采用旧值**（默认值恒在，不能以默认值判断「已设置」），4 项迁移单元测试 |
| 占位菜单清理 | 删除 Contents... / License Agreement... 占位项；Help 菜单改为 **Check for Updates**（补上此前缺失的更新器 UI 入口！）/ Project Homepage（指向真实仓库）/ Version History（Releases 页）/ Language / About |
| 文档同步 | README.md（功能/开发约定/发版指引）、RELEASE.md（发版 SOP）、.zcodeignore 自定义忽略 |
| 本地 CI | `run_checks.bat`：compileall + pytest + GUI 离屏冒烟（`tools/smoke_ui.py`），发布前必须全绿 |
| 打包配套 | 新增 `core/paths.py`（冻结模式路径感知：exe 目录=用户数据，_internal=只读资源），settings/library/图标/机型库全部接入——否则 exe 模式读写错目录；`build.py` 排除 pandas 可选依赖（matplotlib/numba/sqlalchemy/lxml/PIL 等），包体 349MB → **177MB**（zip 82.7MB） |
| 冻结验证 | exe offscreen 启动存活；updater.exe 后台模式端到端（坏源优雅退出+落日志） |

### 0.2 v1.0.0 发布记录（2026-09-27）

- `core/version.py` → 1.0.0；`python build.py` → `dist/WindAnaly/`
- `WindAnaly-1.0.0.zip`（82.7 MB）sha256
  `c26eebcdda36e0e92c7ba642aed4d36b658af6a16b740701ee83d12e3e9dfa9b`
- Release 资产：`WindAnaly-1.0.0.zip` + `versions.json`（见 `release/versions.json`），
  标签 `v1.0.0`，仓库 https://github.com/kyarazhan/WindAnaly

**遗留兼容项**（有意保留，见 §3 债务 D2/D8）：台账库文件名仍为 `windkit.db`；
`_OLD_ZH_TO_EN` 迁移表中个别旧词条未清理（无害）。

---

## 1. 现状架构

### 1.1 分层

```
windanaly.py          唯一入口（更新交接 + QApplication 装配）
├── app.py            AnalysisApp 主窗口（2,003 行：菜单/工具栏/8 Tab/动作分发）
├── core/             纯计算与数据层（无 UI 依赖，可独立测试）★迁移友好
│   ├── 数据模型      dataset.py · project.py · library.py · settings.py
│   ├── 导入引擎      io_import.py（1,702 行，异构格式解析）
│   ├── 分析算法      wind_rose · diurnal · histogram · iec · extreme_wind
│   │                 turbine_power · wind_power · table_stats · mcp_algorithms
│   │                 calculated_columns
│   └── 支撑          i18n.py（903 词条）· db_transfer.py · version.py
├── ui/
│   ├── modules/      8 个分析 Tab + PlotCanvas 自绘引擎（10 文件 10,797 行）
│   ├── dialogs/      34 个功能对话框（10 文件 13,351 行）
│   └── update_tools.py / fallback_bar.py / toolbar_icons.py / theme.qss
└── updater/          独立更新器源码（打包为 updater.exe，与主程序解耦）
```

### 1.2 核心数据流

```
原始数据文件 (txt/csv/xls/rwd/ndf/...)
    │ core.io_import.parse_file()
    ▼
ParsedData → Dataset（df + channels + flags + calibrations）
    │                ├─ library.py → SQLite 台账库 data/windkit.db
    │                └─ project.py → .windanaly 会话（记录 source + 通道分类 + 标记）
    ▼
AnalysisApp.project.datasets[] ──set_project()──▶ 8 个 Tab
    每个 Tab：ds.df 取数 → core/*.py 计算 → PlotCanvas 自绘（QPainter）
```

### 1.3 规模与热点

| 层 | 文件数 | 行数 | 说明 |
|---|---|---|---|
| core/ | 18 | 5,978 | 分层最干净，有测试覆盖 |
| ui/modules/ | 10 | 10,797 | plot.py 2,639 行是最大单文件 |
| ui/dialogs/ | 10 | 13,351 | revise_dialogs 2,692 行居首 |
| app.py | 1 | 2,003 | 菜单构建+动作分发+项目 IO 全在一文件 |
| updater/ | 4 | 1,659 | 与 WindVault_QT 同源，成熟稳定 |
| tests/ | 9 | 762 | 50 项回归，覆盖 core 主算法 |

---

## 2. 主要问题诊断（按影响排序）

**P1 巨型文件 / 上帝类。** `revise_dialogs`、`plot`、`export_dialog`、`app`、
`analysis_dialogs`、`analysis_tabs` 六个文件均 >1,800 行。改一处要在数千行里
定位上下文，review 与合并冲突成本高，是迭代变慢的根因。

**P2 双语底座混乱。** 全库约 2,022 行非 `tr()` 的中文直写（含 docstring/日志，
粗计），其中相当一部分是用户可见 UI 文案：一部分控件以中文为底座走
`i18n.py` 的 zh→en 反查，另一部分以英文为底座走 en→zh 正查，两套并存，
翻译覆盖不齐（新增对话框大量硬编码中文，英文模式下漏翻）。

**P3 app.py 职责过载。** 主窗口同时承担：菜单/工具栏构建、最近文件管理、
项目 IO、数据装载合并、子窗口管理、更新混入。任何功能迭代都要动它。

**P4 PlotCanvas 承担过多图型。** 8 种图型（line/bar/histogram/scatter/polar/
table/heatmap/box）+ 交互（缩放/平移/导出/属性）集中在 2,639 行里，极坐标
（风玫瑰）与直角坐标逻辑互相纠缠。

**P5 测试覆盖偏科。** 50 项测试集中在 core 算法；UI 层 0 覆盖，导入引擎
io_import 仅靠既有用例间接覆盖，回归靠手测。

**P6 无版本管理纪律。** 项目此前不在 git 中（本轮已补 .gitignore，建议尽快
`git init` 后按 §5.2 的提交纪律工作）；历史脚本堆在 `_src/`（已清除）。

**P7 功能缺口**（2026-09-27 复核修正——旧档清单大半已过时）：
~~MCP 缺 4 算法~~（已实现，`mcp_algorithms.py` 共 8 种且对话框全量暴露）；
~~计算列类型不全~~（已实现 11 种，含 Accumulation/Moving Avg/Piecewise/
Polynomial/REWS/Solar）；~~数据库 SQL 导入导出占位~~（`db_transfer.py` +
LinkLibraryDialog 已落地）。**真实剩余**：ASC/ROW/NDF/RLD/Triton 仅有
格式识别与通用解析兜底，无专用解析器（注册表已就位，缺格式规范与 fixture）。

---

## 3. 技术债清单

| 编号 | 债务 | 位置 | 建议批次 |
|---|---|---|---|
| D1 | settings 键名残留 `windrefine_*` | core/settings.py、app.py | S1（改名+迁移函数，一次到位） |
| D2 | 台账库文件名仍叫 `windkit.db` | core/library.py | 保留（数据兼容优先，不改） |
| D3 | i18n 双向字典 + 硬编码中文混用 | core/i18n.py、各 dialogs | S2（统一英文底座） |
| D4 | `_placeholder` 占位动作（License 等 7 处） | app.py 菜单 | S1（删或实现） |
| D5 | dataset.py 缺少序列化版本号（payload 'version':2 在 project 层） | core/project.py | S3（项目格式 v3 契机） |
| D6 | plot.py 无单元测试 | tests/ | S2 |
| D7 | 导出文件头注释旧品牌已改，但导出格式无快照测试 | ui/dialogs/export_dialog.py | S2 |
| D8 | `data/settings.json` 与代码 `_DEFAULTS` 漂移风险（无 schema 版本） | core/settings.py | S3 |
| D9 | quick 别名：`app._open_data_dialog` 等命名残留历史语义 | app.py | S2 随手改 |
| D10 | fallback_bar 自绘菜单栏与原生 QMenuBar 双轨 | ui/fallback_bar.py | S3（评估只留一条路径） |

---

## 4. 自动更新机制（本轮已换代，发版 SOP）

与 WindVault_QT 完全同机制：**独立更新器进程 + 多源版本索引 + 全量/增量包 +
更新前自动备份**。

### 4.1 组成

| 组件 | 位置 | 职责 |
|---|---|---|
| updater.exe | `updater/updater_main.py` → PyInstaller onefile | 独立进程完成查源/选版本/下载(sha256 校验)/关主程序/备份/替换/重启；tkinter UI，纯标准库，可脱离主程序双击自救 |
| 版本索引 | `updater/feed.py` | 按源拉取 `versions.json`（多版本+全量/增量+changelog）；支持 GitHub Releases 网页解析、HTTP、UNC/本地路径三种源 |
| 更新源配置 | `updater/sources.json` | 发版前改这一个文件即可（无需动代码）；兜底源 GitHub Releases |
| 主程序侧 | `ui/update_tools.py` | 启动时后台拉起更新器静默查询；发现新版只在状态栏提示；「帮助→检查更新」前台拉起 |
| 入口交接 | `windanaly.py` | 启动时发现 `.update/pending.json` → 交给 updater.exe（无更新器时 bat 兜底） |

### 4.2 用户数据保护

- `data/` 下 `settings.json`、`windkit.db`、`turbines.json` 更新时**永不覆盖**；
- 每次安装前自动备份 `data/` → `data/backups/pre_update_<时间戳>.zip`，
  按设置保留最近 N 份；更新器界面内可一键「从备份恢复」。

### 4.3 发版 SOP

1. `core/version.py` 改版本号 + 填更新说明；
2. `python build.py` → `dist/WindAnaly/`（主程序 onedir + updater.exe）；
3. 整目录压缩为 `WindAnaly-<版本>.zip`，计算 sha256；
4. 上传到更新源（GitHub Release 资产 / 内网 HTTP / NAS），同目录放
   `versions.json`：
   ```json
   {"versions": [{
     "version": "1.0.1", "date": "2026-10-01",
     "changelog": "修复……",
     "full":  {"url": "WindAnaly-1.0.1.zip", "sha256": "..."},
     "patch": {"base": "1.0.0", "url": "1.0.0-1.0.1-patch.zip", "sha256": "..."}
   }]}
   ```
   （增量包：对上一版安装目录做文件级 diff 打 zip，命名 `<旧>-<新>-patch.zip`；
   后续可按 WindVault_QT 的 `release.py` 思路写自动化脚本，见 S4）
5. ⚠️ **发布前必须确认** `updater/sources.json` 的仓库指向真实存在的
   `kyarazhan/WindAnaly`（当前为占位默认值，仓库尚不存在，首次发版时创建
   或改为内网源）。

---

## 5. 迭代路线图

原则：**每批结束都有可发布版本**；core 层改动必带测试；UI 重构以
「行为不变 + 截图/冒烟对比」为准绳。

### S1 · 止血与规范（0.5~1 周，低风险）

1. `git init` + 提交新基线（.gitignore 已就位）；约定分支/提交纪律；
2. settings 键 `windrefine_*` → `analy_*`，带一次性迁移（读旧写新）；
3. 清理 `_placeholder` 菜单项（删除或明确排期）；
4. 修 `.zcodeignore`/文档同步（本规划书 + ARCHITECTURE.md 入库）；
5. 补 CI 脚本（哪怕只是本地 `run_checks.bat`：compileall + pytest + 冒烟）。

### S2 · 巨型文件拆分（2~3 周，行为不变）

按依赖从叶子往根拆，每拆一个文件跑全量测试 + 离屏冒烟：

| 目标 | 拆法 |
|---|---|
| `app.py` (2,003) | 菜单构建 → `ui/menus.py`；项目 IO/最近文件 → `ui/project_io.py`；数据装载合并 → `core/loader.py`；主窗口只留装配与动作分发（目标 <800 行） |
| `revise_dialogs.py` (2,692) | 按 7 个对话框一文件拆到 `ui/dialogs/revise/` |
| `plot.py` (2,639) | 拆 `plot/canvas.py`（交互）+ `plot/cartesian.py` + `plot/polar.py` + `plot/render.py`（导出/图例） |
| `export_dialog.py` (2,094) | 10 种格式 → 每格式一 writer 类，`ui/dialogs/export/` |
| `analysis_dialogs.py` (1,964) | 16 个对话框按菜单语义拆 3~4 个文件 |
| `analysis_tabs.py` (1,808) | Tab 壳与共享控件分离 |
| i18n 统一英文底座 | 新拆文件一律英文 literal + `tr()`；中文直写的 UI 文案逐个翻译入字典（导出对照表批量处理） |

### S3 · 内功优化（2 周，可与 S2 穿插）

1. **性能**：Time Series LOD 抽稀与 table_stats 聚合做 profile（py-spy），
   大数据集（1 年 10min × 30 通道）打开/刷新目标 <1.5s；
2. **项目格式 v3**：带 schema 版本 + 单独迁移函数（D5/D8），
   `.windanaly` 内嵌 data/windkit.db 通道快照可选；
3. **io_import 插件化**：格式解析器注册表制，新格式（ASC/ROW/NDF/RLD…）
   各自独立模块 + 各自 fixture 测试；
4. **UI 冒烟测试框架**：把 `_smoke.py` 思路固化为 `tests/test_smoke_ui.py`
   （offscreen 模式，冒烟 8 Tab + 主要对话框构造），纳入回归。

### S4 · 功能迭代（持续，按价值排序）

1. ~~MCP 补齐 4 算法~~（复核：8 种已全部实现并有对话框入口）；
2. ~~计算列类型补全~~（复核：11 种已实现）；
3. 报告模板（Templates）与报告版式对齐 Windographer；
4. ~~发布自动化 `release.py`~~（✅ 1.0.3 完成：`tools/release.py <版本>
   --notes "说明"` 一条龙出完整包/增量包/versions.json，基线自动重演）；
5. ~~数据库 SQL 导入/导出~~（复核：db_transfer + 台账库链接已落地）；
6. 新增导入格式专用解析器（ASC/ROW/NDF/RLD，注册表已就位，按需补）。

### S5 · 远期方向（评估后再立项）

- **分发瘦身**：学习 WindVault_QT 的「boot.exe + `_internal/` 运行时 + `app/*.pyc`
  业务码」模块化分发，日常发版只出 KB 级增量包；
- **性能热点 C++ 化 / numpy 向量化**：core 层已无 UI 依赖，是唯一需要动的层；
- **多语言扩展**：i18n 英文底座统一后，加语言只是加字典。

---

## 6. 风险与对策

| 风险 | 对策 |
|---|---|
| 更新源仓库不存在导致首版更新失败 | 首发前创建 GitHub 仓库或改 sources.json 为内网源（§4.3 第 5 步） |
| 老用户 `.windrefine` 项目打不开 | 已兼容双扩展名打开；保存统一 `.windanaly` |
| 拆文件引入行为回归 | 每文件一拆一测；UI 冒烟脚本纳入回归；重构批次不夹带功能改动 |
| 设置键迁移丢用户配置 | 迁移函数「读旧写新」幂等，迁移前后 settings.json 快照对比测试 |
| 台账库结构变动破坏旧库 | library.py 保持只增不改列；任何 schema 变更写迁移 SQL 并留档 |

---

*本规划书随迭代滚动更新；每完成一批在 §0 追加记录。*
