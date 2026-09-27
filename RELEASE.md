# 发版 SOP（Release）

以 v1.0.0 为例。前提：`run_checks.bat` 全绿。

## 1. 版本号

`core/version.py` 改 `VERSION`（更新器、关于对话框、发布脚本共用此值）。

## 2. 打包

```bat
python build.py
:: 产物：dist\WindAnaly\WindAnaly.exe + updater.exe + _internal\
```

## 3. 出发布物

```bat
:: 整目录压缩（顶层含 WindAnaly/ 文件夹，更新器解压时自动去前缀）
python -c "import shutil; shutil.make_archive('WindAnaly-1.0.0','zip',root_dir='dist',base_dir='WindAnaly')"

:: sha256（写入 versions.json）
certutil -hashfile WindAnaly-1.0.0.zip SHA256
```

## 4. versions.json

更新器优先读 Release 资产里的 `versions.json`（多版本索引）。模板：

```json
{
  "versions": [
    {
      "version": "1.0.0",
      "date": "2026-09-27",
      "changelog": "本版更新说明（展示在更新器里）",
      "full":  {"url": "WindAnaly-1.0.0.zip", "sha256": "<上一步的哈希>"},
      "patch": {"base": "0.9.0", "url": "0.9.0-1.0.0-patch.zip", "sha256": "..."}
    }
  ]
}
```

- `full` 必填；`patch` 可选（增量链，命名 `<旧>-<新>-patch.zip`）
- `url` 写相对文件名即可（按索引所在目录解析）
- 文件头 `# Created by ...` 无关；JSON 语法必须严格

## 5. 发布到 GitHub

```bat
git tag v1.0.0 && git push origin main v1.0.0
:: 用 gh（若已安装）：
gh release create v1.0.0 WindAnaly-1.0.0.zip versions.json ^
  --title "WindAnaly 1.0.0" --notes "见 versions.json 的 changelog"
:: 或网页 https://github.com/kyarazhan/WindAnaly/releases/new 上传两个资产
```

资产名必须是 `WindAnaly-<版本>.zip` 与 `versions.json`
（更新器按精确名识别全量包、按名取 versions.json）。

## 6. 验证

装旧版本的机器启动软件 → 状态栏应提示新版本；或直接双击 updater.exe →
「检查更新」应列出刚发的版本 → 更新后重启为新版且 data/ 用户数据保留。

## 增量包制作（可选，未自动化）

对上一版 `dist/` 与新版做文件级 diff（新增/变更文件，排除 data/ 与
`updater.exe.old`），按原目录结构打 zip；`_internal/` 不变则不进包。
