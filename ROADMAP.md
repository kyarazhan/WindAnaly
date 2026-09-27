# WindAnaly 第二阶段规划书（ROADMAP）

> 版本：v1.0 · 2026-09-27 · 基线：软件 v1.0.5（tag v1.0.5，69 项测试全绿）
> 前序文档：[REFACTOR_PLAN.md](REFACTOR_PLAN.md)（第一阶段 S0–S5 历史记录）
> 本文档是第二阶段的滚动规划：每完成一批在 §6 更新记录，随迭代维护。

---

## 1. 现状基线（2026-09-27，v1.0.5 时点）

### 1.1 已完成里程碑

| 阶段 | 内容 | 产物 |
|---|---|---|
| S0 重组 | 去 WindVault、目录提升、品牌统一 WindAnaly | 根级 core/ ui/ updater/ |
| S1 规范 | git 化、设置键迁移、run_checks、README/RELEASE | 65→69 项测试体系起步 |
| 更新器 | WindVault_QT 同款独立 updater.exe；独立模式两处误判已修 | app_version.txt 溯源 |
| S2 拆分(4/6) | app.py 875 行；revise/analysis/tabs 三个包 + shim | 导入路径零改动 |
| S3 内功 | io_import 注册表、项目格式 v3、性能达标（导入 1.30s/刷新 0.79s）、UI 冒烟入 pytest | 69 项测试 |
| S4 自动化 | tools/release.py 一条龙（完整包/基线重演/增量 diff/索引） | 发版手工仅剩 push+上传 |
| S5 第一步 | 模块化分发：boot 桩 + _internal 运行时 + app/*.pyc（77 文件） | 完整包 82.7→61.9 MB |

### 1.2 量化现状

| 指标 | 数值 |
|---|---|
| 代码规模 | 98 个 .py / 37,267 行 |
| 测试 | 15 个文件 / 69 项（含 GUI 冒烟、更新器安装校验） |
| >800 行文件 | 16 个（最大 plot.py 2,639） |
| ui/ 非 tr() 中文文案 | 粗计 211 行（旧估算 2,022 含注释虚高） |
| 已发布版本 | 1.0.0–1.0.5（6 个 tag，GitHub Releases 增量链可用） |

### 1.3 遗留问题（本阶段要解决的）

| 编号 | 问题 | 影响 |
|---|---|---|
| L1 | **补丁体积阻塞**：PyInstaller 产物不可复现（内嵌时间戳），WindAnaly.exe（10MB）/updater.exe（11.65MB）/base_library.zip（1.33MB）每次构建字节全变，diff 永远把它们打进补丁——1.0.5 补丁 21.7MB 中业务真实变更仅 ~0.1MB | 用户下载带宽浪费；补丁机制价值未完全兑现 |
| L2 | plot.py（2,639 行，PlotCanvas 单类 79 方法）与 export_dialog.py（2,094 行，11 个格式 Tab 类）未拆 | 改动热点定位难、review 成本高 |
| L3 | ui/ 约 211 行中文硬编码未走 tr()，英文模式漏翻 | 英文用户体验 |
| L4 | 无 CI：回归依赖本机手工 run_checks | 主干保护缺位 |
| L5 | ASC/ROW/NDF/RLD 仅识别+通用兜底，无专用解析 | 厂商格式支持不完整 |
| L6 | 报告模板（Templates）未立项 | 用户价值 |
| L7 | 构建日志噪音：hidden-import `feed`/`version` 找不到（updater 兄弟模块名被误当运行时依赖） | 干扰构建诊断 |

---

## 2. 阶段主题与目标

| 主题 | 内容 | 度量目标 |
|---|---|---|
| **T1 交付效率** | L1 构建缓存 + L7 构建噪音；日常补丁 KB~MB 级 | 仅改业务码的补丁 **<2MB**；缓存命中构建 **<30s** |
| **T2 主干保护** | L4 GitHub Actions CI | push 后 15 分钟内绿/红反馈 |
| **T3 可维护性** | L2 两巨文件拆分 + L3 i18n 收官 | >800 行文件 16→14；i18n 审计输出 **0** |
| **T4 用户价值** | L5 导入格式、L6 报告模板 | ASC 专用解析落地；模板方案评审 |
| **T5 远期储备** | 性能向量化、多语言、运行时精简 | 立项评估文档 |

---

## 3. 批次详规

> 排批原则：每批结束都有可发布版本；core/ui 结构改动必带测试；
> 拆分类批次「行为不变」，功能类批次「小步快跑」。

### B1 · 构建缓存与 KB 级补丁（→ v1.0.6）★本阶段最高优先

**目标**：业务码变更的日常补丁从 21.7MB 降到 **2MB 以内**（预期 <1MB）。

**根因**：S5 模块化后 app/*.pyc 层已按 diff 正确工作（1.0.5 补丁里只有 2 个
小 .pyc），但 PyInstaller 每次构建的 `WindAnaly.exe`、`updater.exe`、
`_internal/base_library.zip` 字节全变（内嵌时间戳/归档元数据），文件级 diff
必然把它们当"变更"。

**方案：输入指纹 + 产物缓存复用**（不做 PyInstaller 可复现构建——不受我们控制；
只要"输入不变就不重建"，diff 自然稳定）。

1. **主程序运行时指纹**（`build.py` 新增 `_runtime_fingerprint()`）：
   ```
   fp = sha256(
     boot_frozen.py 内容
     + 排序后的 hidden-imports 清单（_scan_hidden_imports 现有输出）
     + 排序后的 excludes 清单
     + 每个 add-data 文件的 sha256（ui/theme.qss、updater/sources.json、
       data/turbines.json、icon.png、icon.ico）
     + PyInstaller.__version__ + sys.version
   )
   ```
   注意：业务源码**不在**指纹里——它们本来就走 app/ 层，与运行时无关。
2. **缓存目录** `build/cache/runtime-<fp[:12]>/`：存 `WindAnaly.exe` +
   `_internal/` 整树。构建流程改为：
   ```
   fp = _runtime_fingerprint()
   cache = build/cache/runtime-<fp[:12]>
   if exists(cache):                     # 命中
       copytree(cache → dist/WindAnaly)   # 覆盖 exe 与 _internal/
       log('运行时: 缓存命中 (<fp12>)')
   else:                                 # 未命中
       staged PyInstaller 构建（现有流程）
       copytree(dist/WindAnaly/{WindAnaly.exe,_internal} → cache)
       清理旧缓存，保留最近 2 份
   ```
3. **updater.exe 同理**：指纹 = `updater/*.py`（updater_main/feed/config/
   version/__init__）+ `updater_icon.ico` + updater.spec 内容 + 工具链版本；
   缓存 `build/cache/updater-<fp12>/updater.exe`。
4. **业务层永远现编译**：`_compile_app_layer` 不参与缓存（每次全量重编，
   ~1s）；`data/app_version.txt` 每次按当前 VERSION 写入。
5. **安全网**：release.py 的 exe 冒烟在缓存命中路径上照常执行——缓存若因
   环境漂移损坏，会在发布前被冒烟拦住；指纹含工具链版本，Python/PyInstaller
   升级自动失效重建（产生一次大补丁，可接受并记录）。
6. **顺手项（L7）**：`_scan_hidden_imports` 过滤 updater 包的兄弟模块名
   （`feed`/`version`），消除两条 hidden-import 警告。

**验收标准**：
- 改一个业务 .py → build → `WindAnaly.exe`/`updater.exe`/`base_library.zip`
  与上一版字节一致（diff 不再收录），补丁仅含 app/*.pyc + app_version.txt；
- 连续两个仅改业务码的版本，第二个补丁 **<2MB**；
- 缓存命中的 build 总耗时 **<30s**；未命中路径行为与现版本一致；
- hidden-import 警告 0 条。

**预估**：0.5~1 天。

### B2 · GitHub Actions CI（→ v1.0.7）

**方案**：`.github/workflows/ci.yml`
- 触发：push（main）+ pull_request；`runs-on: windows-latest`（GUI 依赖
  PySide6/Windows 语义，与发布环境一致）；
- 步骤：checkout → setup-python 3.14（pip 缓存）→ `pip install -r
  requirements.txt`（去掉 pyinstaller 行，CI 不打包）→
  `python -m compileall …` → `python -m pytest tests -q`
  （tests/test_smoke_ui.py 自带 offscreen 环境）；
- README 加 badge；`git tag v*` 推送时追加一个 build workflow 产出 dist
  artifact（供人工复核发布物，不自动发版）。
- 注意：requirements.txt 中 pyinstaller 拆到可选注释行或
  `requirements-build.txt`，CI 不装。

**验收**：push 到 main 触发并在 15 分钟内给出结论；故意引入语法错误的
PR 显示红。

**预估**：0.5 天。

### B3 · export_dialog 拆分（→ v1.0.8）

**现状**（拆分条件已成熟，结构天然）：9 个模块级 helper +
`_CommonOptions` + 11 个格式 Tab 类（_TimeSeriesTab/_WasPTab/_WindSimTab/
_MeteodynWTTab/_OpenwindTab/_WindFarmerTab/_EPETab/_MGMTab/_SAMTab/
_XMLMetadataTab）+ `ExportDataDialog` 门面（仅 4 方法）。

**方案**：`ui/dialogs/export/` 包
```
_common.py      helpers + _CommonOptions（+ 各 Tab 共用常量）
time_series.py  _TimeSeriesTab        wasp.py      _WasPTab
windsim.py      _WindSimTab           meteodyn.py  _MeteodynWTTab
openwind.py     _OpenwindTab          windfarmer.py _WindFarmerTab
epe.py          _EPETab               mgm.py       _MGMTab
sam.py          _SAMTab               xml_meta.py  _XMLMetadataTab
```
`export_dialog.py` 保留门面 `ExportDataDialog`（130 行内），Tab 类从包导入
（对外仅需 `ExportDataDialog` 一个名字，无 shim 负担）。顺手在
`__init__.py` 落一个 `EXPORT_TABS` 注册表（key/类/标题），门面按注册表
构建——新格式（如 WindPRO）零侵入接入。

**验收**：run_checks 全绿（含冒烟里的 ExportDataDialog 构造）；门面行数
<150。

**预估**：0.5 天（沿用 S2 模板化行段搬移脚本）。

### B4 · plot.py 拆分（→ v1.1.0，与 B5 同版）

**现状**：`PlotCanvas` 单类 79 方法（~2,060 行）+ `PlotPropertiesDialog`
（9 方法）+ `ExportImageDialog`（6 方法）+ 模块级 PALETTE/CMAPS/
_EPOCH_ORDINAL/_coerce_x_axis/_decimate_xy/_root_base。

**方案**：`ui/modules/plot/` 包，门面类保留（对外 `from
ui.modules.plot import PlotCanvas` 不变——views/widgets 12 处引用零改动）：

| 文件 | 内容（Mixin 分组） | 预计行数 |
|---|---|---|
| `_common.py` | PALETTE/CMAPS/_EPOCH_ORDINAL/_coerce_x_axis/_decimate_xy/_root_base | ~120 |
| `canvas.py` | PlotCanvas 门面：__init__/尺寸/事件绑定/paintEvent 分发，继承下列 Mixin | ~300 |
| `cartesian.py` | 笛卡尔图型绘制：line/lines/bar/histogram/box/heatmap/scatter + 轴刻度 | ~700 |
| `polar.py` | 风玫瑰：扇区计算/系列样式/图例面板 | ~450 |
| `interact.py` | 缩放/平移/拾取/十字线/坐标 HUD | ~350 |
| `exporting.py` | 导出图片/导出数据/打印 | ~200 |
| `properties.py` | PlotPropertiesDialog | ~260 |
| `export_image.py` | ExportImageDialog | ~180 |
| `plot.py` | shim（re-export PlotCanvas/两对话框/_EPOCH_ORDINAL） | ~15 |

**执行步骤**（沿用 S2 方法论）：① AST 列 79 方法清单按语义人工分桶
（0.5d）→ ② 行段搬移脚本生成包（0.5d）→ ③ 全量 checks + 冒烟
（0.5d）。**新增验收项**：`tests/test_plot_render.py` offscreen 渲染
line/scatter/polar 三图，断言不抛错且产出非空图片（为后续重构兜底）。

**验收**：69+ 项测试与新增渲染测试全绿；`plot.py` 变 shim；canvas 门面
<400 行。

**预估**：1~1.5 天。

### B5 · i18n 收官（→ v1.1.0 同版）

- 新增 `tools/i18n_audit.py`：AST 级扫描 `ui/` 与 `app.py` 中用户可见
  中文直写（排除注释/docstring/日志/异常内部消息），输出文件+行清单；
  接入 run_checks（阈值 0 + 白名单文件机制）；
- 现存 ~211 行逐条修复：英文底座 literal + `tr()`，词条入
  DEFAULT_TRANSLATIONS（可先用导出对照表批量翻译）；
- 验收：审计输出 0；中/英两模式冒烟各跑一遍无异常。

**预估**：0.5~1 天。

### B6 · 导入格式扩展 ASC / ROW / NDF（→ v1.1.x，先调研后立项）

- **现状**：三种格式仅 `detect_special_format` 识别 + 通用解析兜底；
  注册表（S3-3）已就位，缺的是专用解析器与样例。
- **调研项**（动工前置条件，缺一样不立项）：
  | 格式 | 规范来源候选 | 风险 |
  |---|---|---|
  | ASC | NRG Symphonie DATA/CHAN/CAL 文本结构（Windographer 文档、NRG 官网） | 低（文本格式） |
  | ROW | SecondWind Triton 规范（二进制，可能需 NDA/样例） | 高 |
  | NDF | NRG Nomad2 二进制规范 | 高 |
- **交付形态**：每个格式一个 `_parse_xxx` + match 谓词 + 注册区一行
  （S3-3 注册表零改动接入）；fixture 样例文件入 `tests/fixtures/` +
  解析断言测试（通道数/高度/首尾时间戳）。
- NDF 若规范不可得：维持「识别 + 引导用户官方导出」现状并关闭该项。

**预估**：ASC 1 天；ROW/NDF 各 1~3 天或搁置。

### B7 · 报告模板 Templates（→ v1.2.0，本阶段只立项）

- 方向：`data/templates/` HTML 模板 + 占位符（{{site}}、{{period}}、
  {{tables}}、{{figures}}…），报告对话框加模板下拉；report_builder 已有
  HTML/DOCX 双通道可挂接。
- 本阶段仅产出设计稿（占位符清单、默认模板、与 windrose/tables 的数据
  接口），实现排入下阶段。

### T5 · 远期储备（不排期，条件触发）

- **性能向量化**：仅当 bench.py 回归劣化 >30% 时立项（当前已达标）；
- **多语言**：i18n 收官后新增语言 = 翻译字典 + language 菜单项；
- **运行时精简**：分析 _internal/ 大头（PySide6 ≈2/3），评估 Qt 模块
  按需裁剪；
- **安装器**：Inno Setup 首装包（exe + 关联 .windanaly + 开始菜单），
  用户量起来再立项。

---

## 4. 版本与发布节奏

| 版本 | 批次 | 性质 |
|---|---|---|
| 1.0.6 | B1 构建缓存 | 工具链（补丁体积验证版） |
| 1.0.7 | B2 CI | 工具链 |
| 1.0.8 | B3 export 拆分 | 重构（行为不变） |
| 1.1.0 | B4+B5 plot 拆分 + i18n 收官 | minor（内部架构收官） |
| 1.1.x | B6 格式解析（每个格式一版） | minor（用户价值） |
| 1.2.0 | B7 报告模板 | minor（用户价值） |

发布 SOP 不变：`run_checks.bat` 全绿 → `core/version.py` → `python
tools/release.py <版本> --notes "…"` → push/tag → GitHub Release 只传
增量包；本地 `release/` 三件套留存。

---

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| 缓存命中但运行时实际损坏（磁盘/拷贝问题） | release.py 冒烟在缓存命中路径照常执行，坏缓存发布前被拦 |
| Python/PyInstaller 升级导致一次性大补丁 | 指纹含工具链版本自动失效重建；发版说明注明 |
| plot 拆分引入渲染回归 | 新增渲染冒烟测试先行（B4 第一步）；mixin 机械搬移不改逻辑 |
| CI 与本机环境差异（字体/平台插件） | 冒烟已 offscreen 化并在本机验证；runner 固定 windows-latest |
| ASC/ROW/NDF 规范不可得 | 调研前置、拿不到就不立项（NDF 维持引导导出现状） |
| 业务 .pyc 与运行时 Python 版本绑定 | 缓存指纹含 sys.version；换 Python 必然全量重建 |

---

## 6. 批次记录（滚动更新）

- （待填：B1 → v1.0.6）

---

## 7. 度量看板（每批发布后更新）

| 指标 | 基线（v1.0.5） | 目标 |
|---|---|---|
| 仅业务码变更的补丁体积 | 21.7 MB | **<2 MB** |
| 缓存命中的构建耗时 | ~2.5 min | **<30 s** |
| 测试项数 | 69 | **≥85**（+plot 渲染、+解析器、+i18n 审计） |
| >800 行文件 | 16 | **14**（plot/export 转 shim） |
| i18n 审计输出 | ~211 行 | **0** |
| CI | 无 | push 即检 |
