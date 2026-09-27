# WindAnaly

测风塔数据风资源分析软件（Windows 桌面单机版）。对标 Windographer 的工程
工作流：载入各厂商测风原始数据 → 通道分类与质控标记 → 风资源分析 →
报告与多格式导出。基于 PySide6 + pandas/numpy，自绘绘图引擎，零重型依赖。

## 功能总览

- **8 个分析视图**：Summary / Time Series / Wind Rose / Diurnal Profile /
  Histogram / Scatter Plot / Data Table / Report
- **分析对话框**：数据恢复率、湍流（IEC 61400-1）、风切变、Weibull 分布、
  塔影畸变、温度廓线、风机出力/AEP、入流角、风功率等级、短期距、长期分析
  （MCP 基础算法）、超越概率、极端风（PM/MOS/EWTS II）、代表年、预测误差等
- **数据修正**：比例/偏移、时移、组合风速仪、垂直外推、插补、修复量化等
- **质控标记**：手动/散点/规则/塔影标记，标记注册表与统计
- **导入**：NRG/Symphonie/Nomad2/ZephIR/Windcube 等厂商格式 + 通用
  txt/csv/xls，支持目录递归合并
- **导出**：10 种格式（Time Series / WAsP / WindSim / Meteodyn / Openwind /
  WindFarmer / EPE / MGM / SAM / XML）
- **台账库**：SQLite 台账（登记/序列号/完整率），分析与库互相导入导出
- **自动更新**：独立 updater.exe，多源（GitHub Releases / HTTP / 内网共享）、
  全量+增量包、sha256 校验、更新前自动备份 data/ 用户数据
- **中英双语**：英文底座 + 中文翻译，菜单可切换

## 快速开始

### 开发运行

```bat
pip install -r requirements.txt
python windanaly.py
```

### 检查（提交/发布前必须全绿）

```bat
run_checks.bat        :: 语法编译 + pytest 回归 + GUI 离屏冒烟
```

### 打包发布

```bat
python build.py       :: 生成 dist\WindAnaly\（WindAnaly.exe + updater.exe）
```

发版 SOP 见 [RELEASE.md](RELEASE.md)，架构说明见
[ARCHITECTURE.md](ARCHITECTURE.md)，迭代路线图见
[REFACTOR_PLAN.md](REFACTOR_PLAN.md)。

## 目录结构

```
windanaly.py   唯一入口          core/    纯计算与数据层（无 UI 依赖）
app.py         主窗口            ui/      8 Tab + 对话框 + 绘图引擎
build.py       PyInstaller 脚本  updater/ 独立更新器源码
tests/         回归测试          data/    用户数据（settings/台账库，更新保留）
tools/         冒烟等开发脚本
```

## 开发约定

- 单分支 `main` 开发；提交信息用语义化前缀：
  `feat:` `fix:` `docs:` `refactor:` `test:` `chore:`
- 发版 = 改 `core/version.py` → `run_checks.bat` 全绿 → 打 tag `vX.Y.Z` →
  按 RELEASE.md 出包上传 Release
- core/ 改动必须带 pytest 用例；UI 改动跑冒烟
- `core/`、`updater/` 内禁止直接 import PySide6（保持分层与更新器独立）

## 更新机制（用户侧）

启动时后台静默检查新版本（状态栏提示，不打扰）；「帮助 → 检查更新」打开
独立更新器：可选目标版本、完整包或增量包逐级补齐、自动备份后安装并重启。
`updater.exe` 也可双击独立运行（主程序损坏时自救）。
