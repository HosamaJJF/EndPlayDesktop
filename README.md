# EndPlayDesktop

[English](./README.en.md)

以插件的形式为 PlayCover 中的《明日方舟：终末地》注入修改 PC 界面和进程内键鼠输入，并以补丁形式为 MaaEnd 添加 EndPlayDesktop 控制器，实现在 PlayCover 环境下使用 Windows 控制器的任务，丰富适配的任务类型。本项目独立于 MaaEnd 和 MXU 维护。需要使用带 MaaTool 的社区 fork 版 [PlayCover](https://github.com/hguandl/PlayCover/releases)。

插件存在对游戏注入修改的行为，如在意相关风险请不要使用本项目，本项目不对使用后可能带来的账号损失负任何责任。

## 项目结构

| 路径 | 内容 |
| --- | --- |
| `src/`、`CMakeLists.txt` | 游戏插件源码与构建配置 |
| `tools/EndPlayDesktop/`、`patch.py` | 控制器、截图与补丁工具 |
| `patches/` | MXU 控制器源码补丁 |
| `packaging/` | 一键补丁应用的打包配置 |
| `tests/`、`docs/` | 测试与详细文档 |

## 安装方法

需要先正常安装上述社区版 PlayCover、终末地和 MaaEnd，在 Playcover 中开放 MaaTool 的端口。

1. 前往本仓库的 **Releases**，下载补丁 `.dmg` 和 `libEndPlayDesktop.dylib`。
2. 完全退出游戏，在 PlayCover 中右键终末地，打开 **设置 → 杂项**，添加下载的 `.dylib` 为自定义插件；如已安装旧版 `libUnityDesktopMode.dylib`，先将其移除。
3. **关闭“启用键盘映射布局”**，保持 MaaTool 启用，然后重新启动游戏。
4. 完全退出 MaaEnd，打开 `.dmg` 中的 `EndPlayDesktopPatch.app`，选择已安装的 `MaaEnd.app`，点击“应用补丁”。
5. 重新打开 MaaEnd，选择 **EndPlayDesktop** 控制器，填写游戏的 MaaTools 地址并连接。

补丁保留 MaaEnd 原有功能，为除开启、关闭游戏以外的 Windows 任务添加兼容标记；兼容标记不代表所有任务均已实测。补丁保留目标包自己的 Go/C++ Agent、MaaFramework 与业务资源。MaaEnd 常规更新后，使用同一工具重新应用补丁即可，无需为每个版本重新构建 Agent。使用时保持游戏窗口未最小化和隐藏，可以挂在后台不抢占键鼠。

## 自行构建

需要 Xcode、CMake、Ninja、Git、Node.js 22、pnpm、Rust、tauri 和 uv 环境。在本仓库根目录运行：

```bash
uv sync --group bundle

# 构建游戏插件
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build

# 构建 MaaEnd 补丁，首次运行会下载上游源码和依赖
uv run python patch.py build --app /Applications/MaaEnd.app --mxu-source .cache/sources/MXU

# 打包可复用于后续 MaaEnd 更新的一键补丁
uv run --group bundle python -m tools.EndPlayDesktop.build_app --payload .cache/payloads/desktop
```

插件产物为 `build/libEndPlayDesktop.dylib`；补丁程序位于 `dist/`。

本项目采用 [AGPL-3.0](./LICENSE)，来源说明见[第三方声明](./THIRD_PARTY_NOTICES.md)。
