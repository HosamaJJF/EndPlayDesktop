# 0.0.6 菜单栏图标与后台窗口恢复故障

排查日期：2026-11-16。目标为已安装的 MaaEnd v3.2.0-beta.2，补丁收据为 format 3、Runtime 0.0.6。本机 `sw_vers` 返回版本 27.2.1、构建号 26B131；下述结果来自本机实测。

## 原因

0.0.6 新增的启动器触发了 macOS 经 LaunchServices 启动应用时的菜单栏项注册故障：应用声明的主程序是启动器，随后启动器用 `execv()` 将当前进程替换成另一个 GUI 程序。主窗口仍可正常显示，菜单栏项对象也能创建，但系统没有将其正常放进菜单栏。

代码路径如下：

1. `tools/EndPlayDesktop/adapter_patch.py` 将 `CFBundleExecutable` 从上游程序名改为 `EndPlayDesktopLauncher`。
2. `src/controller/Launcher.mm` 设置本次进程的适配环境，再以 `execv()` 执行原 MaaEnd。
3. MXU 创建托盘并加载图标时可以返回成功。随后关闭窗口仍按已启用的 `minimizeToTray` 设置隐藏主窗口，进程继续运行，恢复窗口的菜单栏入口却不可用。

Apple 开发者论坛记录了相同问题，并链接了只含 AppKit 状态栏项与 C 启动器的最小复现，反馈编号为 FB21015611。Deno 也遇到同类启动链问题，其修复是让实际 GUI 程序直接作为应用主入口。

- [Apple 开发者论坛](https://developer.apple.com/forums/thread/806691)
- [AppKit 最小复现](https://github.com/mkrnr/macos-menu-bar-icon-bug-test-project)
- [Deno 修复及对照证据](https://github.com/denoland/deno/pull/35626)

## 本机证据

安装包的 `Contents/Info.plist` 声明 `CFBundleExecutable=EndPlayDesktopLauncher`，配置中的 `upstream_executable=MaaEnd`；运行进程的实际程序为 `Contents/MacOS/MaaEnd`。

现有 MXU 日志记录了成功加载菜单栏图标、启用后台选项和关闭时隐藏窗口：

```text
[2026-11-16 09:20:44][INFO][mxu_lib::commands::tray] Minimize to tray: true
[2026-11-16 09:20:44][INFO][mxu_lib::tray] Tray icon updated: /Applications/MaaEnd.app/Contents/MacOS/locales/MaaEnd-Tiny.png
[2026-11-16 09:20:47][INFO][mxu_lib] [exit] Window 'main' close requested, minimize_to_tray=true
```

为隔离业务逻辑，在忽略目录 `.cache/macos-tray-validation/` 中创建了三个临时签名应用。它们使用同一个 AppKit 测试程序，只显示窗口与标题为 `EPD probe` 的状态栏项，不加载 MaaFramework、不连接游戏。使用桌面应用启动接口打开 `.app`，经 macOS 正常应用启动流程运行，而非从终端直接执行包内程序。

| 应用入口 | 加载的动态库 | 主窗口 | 状态栏窗口 frame（x, y, width, height） |
| --- | --- | --- | --- |
| 直接执行 `TrayProbe` | 无 | 正常显示 | `(295, 889, 85, 30)` |
| 0.0.6 的 `EndPlayDesktopLauncher` | 当前控制器适配层 | 正常显示 | `(0, 0, 85, 0)` |
| 同一个启动器 | 空动态库 | 正常显示 | `(0, 0, 85, 0)` |

测试屏幕尺寸为 `1323 × 919`。直接入口的状态栏项位于顶部，启动器入口的状态栏窗口高度为 0；空动态库同样复现，说明无需任何控制器适配代码就能触发故障。`NSWindow.isVisible` 在三个版本中均为 true，因此仅检查创建成功或可见标志无法发现问题。

原始探针源码保存在 `.cache/macos-tray-probe.mm`，结果为上述目录中的 `direct.app.json`、`launcher.app.json` 和 `launcher-no-adapter.app.json`。三个探针均自动退出。已安装的 MaaEnd 在界面复现后重新打开，主窗口已恢复；本轮未执行游戏任务，也未改写正式安装包。

## Dock 图标的恢复缺口

菜单栏点击与 Dock 点击经过不同的事件路径。核查 MXU 上游 `04ad07ba056b0198d38b9438c4cdee6a25d251f1` 时，`src-tauri/src/lib.rs` 的运行事件回调只处理退出事件，没有处理 macOS 的 `RunEvent::Reopen`；显示窗口的操作位于 `tray::show_main_window()`。

因此，菜单栏入口失效后，点击 Dock 图标也缺少显式的隐藏窗口恢复处理。该点是源码层面的独立缺口；本轮没有单独记录已安装程序收到 Dock Reopen 事件的运行轨迹。

- [MXU 运行事件回调](https://github.com/MaaXYZ/MXU/blob/04ad07ba056b0198d38b9438c4cdee6a25d251f1/src-tauri/src/lib.rs)
- [MXU 托盘及窗口恢复逻辑](https://github.com/MaaXYZ/MXU/blob/04ad07ba056b0198d38b9438c4cdee6a25d251f1/src-tauri/src/tray.rs)

## 修复方向与验证要求

EndPlayDesktop 应调整适配层的加载方式，让原版 GUI 程序直接保持为 `CFBundleExecutable`，消除应用入口到 GUI 程序之间的 `execv()` 跳转。继续保留目标包自带的 MXU，不依靠替换成旧版 MXU 恢复托盘。具体加载方案需要验证签名、上游更新、重复应用与原包恢复。

MXU 可在 macOS `RunEvent::Reopen` 中复用 `tray::show_main_window()`，为 Dock 重新打开补上窗口显示、取消最小化和聚焦处理。这项修复不能替代菜单栏注册问题的修复。

现有 `tests/controller_adapter_test.py` 使用 `subprocess.run()` 直接执行启动器，绕过了出现故障的 LaunchServices 路径。后续回归必须从 Finder、Dock 或等效的正常应用启动入口启动 `.app`，检查菜单栏项实际挂载，并覆盖关闭后通过菜单栏和 Dock 恢复窗口、后台进程保持及正常退出。

## 0.0.7 修复验证

生产载荷已改为 format 4：保留原版应用入口，使用 Mach-O 头部空闲空间加载适配层，并添加 AppKit Reopen 恢复处理。首次安装验证使用同版本未打补丁的官方应用副本；按用户要求，不将旧 0.0.6 状态直接迁移作为交付保证。

- MaaEnd v3.2.0-beta.2 的 31 个有文件内容的 Mach-O section、偏移和构建 UUID 保持一致，完整签名校验及重复应用检查通过。
- 通过正常 `.app` 启动入口打开验证副本后，真实 MXU 的菜单栏窗口 frame 为 `(402, 889, 34, 30)`，已正常挂载。
- 在独立配置中开启“关闭时最小化到托盘”，关闭后主窗口 `visible=false`，进程继续运行；从 Finder 再次打开同一应用后，主窗口 `visible=true`，进程 PID 保持 96348。
- 原始记录位于 `.cache/tray-fix-validation/` 中的 `apply-report.json`、`visible-before-close.json`、`hidden-after-close.json` 和 `visible-after-reopen.json`。验证副本已正常退出，未执行业务任务。
- Reopen 原回调转发与隐藏窗口恢复由 AppKit 原生回归测试覆盖。上述 Finder 重新打开与 Dock 点击使用同类 Reopen 事件；本轮没有通过桌面工具单独点击 Dock 或菜单栏图标。
