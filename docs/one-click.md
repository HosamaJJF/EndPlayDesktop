# 一键补丁工具

[English](./one-click.en.md)

下载并解压 `EndPlayDesktop-0.0.5-macos-arm64.zip`，或打开同名 DMG。面向 Apple Silicon Mac，工具内置所需运行环境和现成补丁，无需安装 Python、uv、Go 或 Rust。

## 应用补丁

1. 完全退出 MaaEnd，游戏可以保持运行。
2. 双击 `EndPlayDesktopPatch.app`。
3. 默认选择 `/Applications/MaaEnd.app`；安装在其他位置时，点击“选择 MaaEnd…”指定应用。
4. 点击“应用补丁”，等待完成提示。
5. 打开原 MaaEnd，选择 EndPlayDesktop 控制器，填写游戏实际 MaaTools 地址并点击连接提交。新配置默认显示 `127.0.0.1:1717`，与原生 PlayCover 一致；已有保存地址保留。

应用名称、MaaEnd 版本号、官方更新源和原任务逻辑保持原样。Windows 任务及上游 PlayCover 启动、关闭游戏任务追加 EndPlayDesktop 兼容标记。目标包自己的 Go/C++ Agent、MaaFramework 与业务资源会保留。MaaEnd 常规更新后使用同一工具重新应用即可，无需按版本重编 Agent；上游协议或框架 ABI 大改时仍可能需要更新补丁。

0.0.2 及更早工具替换过 Go Agent。迁移时会从同版本原包备份恢复；备份已删除时，需先重新安装一次当前官方 MaaEnd，再应用本工具。任务配置无需删除。

工具会替换整个 MXU 可执行文件，当前基于 MXU v2.8.0 构建。MaaEnd 携带新版 MXU 时，应先迁移补丁并重新构建验证，旧补丁不会自动保留新版 MXU 的功能与修复。

## 启动与关闭游戏

使用已包含 PlayCover 启动与关闭任务的 MaaEnd，在 EndPlayDesktop 控制器下添加“启动游戏 (PlayCover)”和“关闭游戏 (PlayCover)”。启动是连接控制器前执行的预任务，不受任务列表排序影响；关闭应放在业务任务之后。任务执行与取消沿用上游流程。

补丁不再添加 EndPlayDesktop 专用任务或 Pipeline。重新应用会清理旧版生成的任务文件、导入和附加资源；已有任务列表中的旧 EndPlayDesktop 启动、关闭任务请替换为对应的 PlayCover 任务，并重新设置所需选项。

游戏路径留空时自动使用当前用户 PlayCover 容器中的 `com.hypergryph.endfield.app`；安装在其他位置时填写完整 `.app` 路径。启动预任务只打开或复用游戏进程，然后等待“启动后等待（秒）”指定的间隔，默认 10 秒，可设为 0 至 300 秒。它不读取连接地址，不检查插件、MaaTools 或截图，也不释放或重建控制器连接。等待不足时可延长间隔；是否连接成功由随后 MXU 的正常连接阶段判断。登录与进入游戏仍由原有任务处理。

地址提交、默认输入值、自动重连、有效连接复用及旧连接清理沿用原生 PlayCover 的规则。仅编辑输入框不会提交地址；没有已保存地址时，开始任务会提示设备配置不足，不再自动补用 1718。关闭任务仍先释放输入，再通过 MaaTools 请求退出；退出等待超时后校验进程身份并发送 SIGTERM，确认进程退出。

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

构建前需已生成 `.cache/payloads/desktop/` 和 `build/libEndPlayDesktop.dylib`。产物位于 `dist/`，包含可双击的应用、ZIP 和 DMG。当前测试包使用本地 ad-hoc 签名，未进行 Apple 公证。
