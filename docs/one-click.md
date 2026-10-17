# 一键补丁工具

[English](./one-click.en.md)

下载并解压 `EndPlayDesktop-0.1.7-macos-arm64.zip`，或打开同名 DMG。面向 Apple Silicon Mac，工具内置所需运行环境和现成补丁，无需安装 Python、uv、Go 或 Rust。

## 应用补丁

1. 完全退出 MaaEnd，游戏可以保持运行。
2. 双击 `EndPlayDesktopPatch.app`。
3. 默认选择 `/Applications/MaaEnd.app`；安装在其他位置时，点击“选择 MaaEnd…”指定应用。
4. 点击“应用补丁”，等待完成提示。
5. 打开原 MaaEnd，选择 EndPlayDesktop 控制器，填写游戏实际 MaaTools 地址并连接。

应用名称、MaaEnd 版本号、官方更新源和原任务逻辑保持原样。Windows 任务追加兼容标记，开启和关闭游戏任务除外。未来 MaaEnd 版本默认继续应用，不做版本或客户端基线兼容拦截。

## 游戏插件

分发包同时提供 `libEndPlayDesktop.dylib`。在 PlayCover 的终末地自定义插件设置中加载它，并保持 MaaTools 启用；更换游戏插件后需要重启游戏。已经使用当前插件时，不必重复安装。具体说明见源码包中的插件文档。

## 备份与恢复

工具将备份、补丁运行环境和日志保存在 `~/Library/Application Support/EndPlayDesktop/`，不会依赖下载目录或开发源码目录。应用完成后可以退出工具、移走下载包或推出 DMG。

需要恢复时，先退出 MaaEnd，再打开工具、选择对应 MaaEnd，点击“恢复备份”并确认。恢复的是上次应用补丁前的状态；更新后的 MaaEnd 可以再次打开工具应用补丁。

## 源码与构建

分发包包含 `EndPlayDesktop-source.zip` 和许可证。开发者可在源码目录执行：

```bash
uv sync --group bundle
uv run --group bundle python -m tools.EndPlayDesktop.build_app
```

构建前需已生成 `.cache/payloads/v2.33.0/` 和 `build/libEndPlayDesktop.dylib`。产物位于 `dist/`，包含可双击的应用、ZIP 和 DMG。当前测试包使用本地 ad-hoc 签名，未进行 Apple 公证。
