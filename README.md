# EndPlayDesktop

[English](./README.en.md)

为 PlayCover 中的《明日方舟：终末地》提供 PC 界面和进程内键鼠输入，并以本地补丁形式为 MaaEnd 添加 EndPlayDesktop 控制器。本项目独立维护，暂不向 MaaEnd 或 MXU 上游提交。

> 本 README 是初稿框架，安装截图、适配版本与发布说明待维护者补充。

## 项目组成

| 路径 | 内容 |
| --- | --- |
| `src/`、`CMakeLists.txt` | PlayCover 自定义插件源码 |
| `tools/EndPlayDesktop/` | 控制器、MaaTools 截图、补丁构建和应用工具 |
| `patches/` | MXU 与 MaaEnd Go Agent 的源码补丁、构建参考版本 |
| `patch.py` | MaaEnd.app 补丁入口 |
| `tests/` | 插件模拟测试 |
| `docs/` | 插件协议与控制器开发说明 |

## 环境准备

需要 Apple Silicon Mac、Xcode（含 Mac Catalyst SDK）、PlayCover 和 MaaTools。构建还需要 CMake、Ninja、Git、Go、Node.js 22、pnpm、Rust、`cargo tauri` 与 uv。

```bash
uv sync
```

待补充：已验证的 macOS、PlayCover、MaaTools 和游戏版本，以及工具安装步骤。

## 构建并加载游戏插件

```bash
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build
ctest --test-dir build --output-on-failure
```

在 PlayCover 的终末地自定义插件设置中，用 `build/libEndPlayDesktop.dylib` 替换旧 `libUnityDesktopMode.dylib`，保持 MaaTools 启用并重启游戏。具体说明见[插件文档](./docs/plugin.md)。

待补充：PlayCover 设置截图、PC 界面示例和 MaaTools 端口查看方法。

## 为 MaaEnd.app 应用补丁

完全退出 MaaEnd，保留原安装包。以下以 `/Applications/MaaEnd.app` 为例：

```bash
# 构建与当前包体版本匹配的补丁；首次需要下载官方源码和构建依赖
uv run python patch.py build --app /Applications/MaaEnd.app

# 查看将修改的文件与兼容范围
uv run python patch.py plan --app /Applications/MaaEnd.app

# 备份原包、应用补丁并重新进行本地签名
uv run python patch.py apply --app /Applications/MaaEnd.app
```

补丁保留原应用名称、图标、标题、项目地址及原控制器，新增独立的 EndPlayDesktop 地址连接选项。MaaEnd 的版本号、官方更新源和更新逻辑保持不变。所有带 Windows 控制器限制的任务及选项追加兼容标记，开启游戏 `LaunchGamePC` 与关闭游戏 `CloseGamePC` 除外。未限制控制器的任务原本就可选。标记兼容不代表每项任务均已实测。

重新打开原 MaaEnd.app，选择 EndPlayDesktop，填写游戏实际 MaaTools 地址。游戏窗口需保持显示且未最小化，可以被其他应用遮挡；玩家仍可手动介入。

待补充：控制器设置截图、推荐游戏设置与人工测试结果。

## MaaEnd 更新与回滚

MaaEnd 更新覆盖补丁后，重新执行 `build`、`plan`、`apply`。资源兼容标记根据新包动态生成；Go Agent 按包体对应的官方源码构建。默认尝试兼容未来所有 MaaEnd 版本，不设置版本或客户端指纹兼容白名单；实际出现补丁应用问题后再调整。MXU `v2.8.0` 是当前默认构建参考，不作为 MaaEnd 兼容上限。

`apply` 输出备份目录。退出 MaaEnd 后，可使用该路径恢复完整原包：

```bash
uv run python patch.py restore --app /Applications/MaaEnd.app --backup /absolute/path/to/backup
```

`backups/`、`.cache/` 和编译产物均不提交。补丁依赖本仓库的 Python 环境；移动仓库后需重新应用补丁以更新运行路径。MaaEnd 用户配置仍由原客户端管理。

## 开发与已知边界

```bash
uv run python -m unittest discover -s tools/EndPlayDesktop -t . -p 'test_*.py'
uv run python -m tools.EndPlayDesktop status
```

控制器说明见[开发文档](./docs/controller.md)。当前不实现游戏启停和文本输入；Maa Pipeline Support 扩展尚不支持此控制器，本项目不修改该扩展。隐藏、最小化和跨 Space 的截图不在保证范围内。

待补充：问题反馈模板、兼容矩阵、版本发布流程。

## 来源与许可

仓库使用 [AGPL-3.0](./LICENSE)，保留 MaaEnd 与 MXU 的来源说明，见[第三方声明](./THIRD_PARTY_NOTICES.md)。游戏程序、原第三方插件及其二进制不包含在仓库中。
