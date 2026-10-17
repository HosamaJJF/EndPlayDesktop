# EndPlayDesktop

[English](./plugin.en.md)

终末地 PlayCover 专用 PC UI 与进程内输入插件。本仓库同时维护游戏内 dylib、`tools/EndPlayDesktop/` 控制器与 MaaEnd.app 补丁。

## 当前范围

- 只在 `com.hypergryph.endfield` 中启动，通过已导出的 IL2CPP 接口按方法签名解析，不依赖旧插件或客户端固定地址。
- 切换游戏 `Beyond.DeviceInfo` 的平台与输入类型，在 Unity Input System 创建虚拟 Keyboard、Mouse。
- 提供 Windows VK、鼠标按钮、绝对位置、相对移动与滚轮；空闲和自动化期间均接收游戏前台的 GameController 键鼠、UIKit 点击、按键与悬停事件。
- 自动化会话临时开启后台更新与 IgnoreFocus，不加入手动接管或暂停切换。玩家与自动化分别记录持键，两者任一来源仍按住时保持按下；结束会话、断连或心跳超时只释放自动化来源并恢复设置，失焦只释放手动来源。
- 同时向 Legacy Input 转发键盘与鼠标按钮，并提供鼠标位置、滚轮、`MouseAxis1/MouseAxis2`。通过当前镜像中的受限 ARM64 模式解析定位未导出的 `UnitySetKeyState` 和 icall 缓存，只替换数据指针；签名不匹配时停止初始化。文本输入与 Metal 截图尚未实现。
- 保留游戏的 `Cursor.visible` 与锁定语义。世界场景中的手动相对位移来自本应用的鼠标事件；宿主光标只在游戏前台且请求锁定时捕获，失焦立即释放。后台自动化不捕获系统光标或激活窗口。

这是一版供实机验证的原型。编译及模拟 IL2CPP 测试通过，不等于游戏内 PC 界面、镜头控制、后台和所有 Windows Pipeline 已验证。

## 构建

需要 Apple Silicon Mac、Xcode（包含 Mac Catalyst SDK）、CMake 和 Ninja。

```bash
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build
ctest --test-dir build --output-on-failure
codesign --verify --strict build/libEndPlayDesktop.dylib
```

产物为 `build/libEndPlayDesktop.dylib`，目标为 arm64 Mac Catalyst，构建后自动进行本地 ad-hoc 签名。模拟 UnityFramework 位于 `build/fixtures/`，只用于测试，不能安装到游戏中。

## 加载与连接

1. 完全退出游戏，在 PlayCover 的终末地自定义插件列表中移除 `libUnityDesktopMode.dylib`，加入本项目生成的 `libEndPlayDesktop.dylib`。
2. 保持 MaaTools 启用，然后从 PlayCover 启动游戏。插件不会修改 PlayTools，也不会自行复制到游戏目录。
3. 插件把监听地址与随机令牌写入当前应用缓存中的 `EndPlayDesktop/endpoint.json`。通常位于 `~/Library/Containers/com.hypergryph.endfield/Data/Library/Caches/EndPlayDesktop/endpoint.json`；实际路径以系统日志的 `[EndPlayDesktop] connection descriptor` 为准。
4. 在 EndPlayDesktop 仓库目录运行 `uv run python -m tools.EndPlayDesktop status`。连接描述未被自动发现时，在 `status` 前添加 `--endpoint /absolute/path/endpoint.json`。

发现旧插件共存时，本插件停止自己的输入并报告冲突。连接文件只供当前用户读取，工具不会输出其中的令牌。

## 本地协议

服务只绑定 IPv4 loopback 的随机端口。每帧为 4 字节大端 JSON 长度加 UTF-8 JSON，最大 64 KiB。第一帧必须为 `hello`，含 `protocol: 1` 与连接文件中的 `token`。同一时刻只允许一个验证后的客户端持有连接。

| op | 字段 | 含义 |
| --- | --- | --- |
| `status` | 无 | 在游戏主线程查询就绪状态、分辨率、输入更新计数和设备回读 |
| `ping` | 无 | 在 socket 线程返回 `ok=true`，仅确认连接存活，不读取游戏状态 |
| `camera` | 无 | 0.1.7 起只读世界相机俯仰、朝向与 FOV；不创建输入会话 |
| `begin` | 无 | 开始自动化会话，保存并改变后台设置；保留前台手动输入 |
| `end` | 无 | 释放自动化持键，恢复后台设置 |
| `key` | `vk`, `down` | Windows VK 按下/释放 |
| `move` | `x`, `y`, `delta` | 游戏原始截图坐标；`delta` 决定是否产生位置差值 |
| `button` | `button`, `down` | 0 左键、1 右键、2 中键、3/4 辅助键 |
| `relative` | `dx`, `dy` | 按渲染分辨率换算的 Windows 桌面位移，传入坐标 Y 向下 |
| `scroll` | `dx`, `dy` | Unity Input System 滚轮增量，具体灵敏度待实测 |
| `release` | 无 | 释放自动化来源已按下的键和按钮 |

除查询外，输入命令必须位于 `begin` / `end` 会话内。请求 3 秒无进展时断开并安排主线程清理。游戏主线程不响应时，未执行的请求被取消；清理在主线程恢复后执行。响应中的 `input_update_count` 来自 Unity Input System，控制器等待它推进后返回，但更新计数不能单独证明事件被消费。`device_state` 从真实 Unity 控件回读鼠标坐标、左键和最近一个键的状态；`available=false` 表示客户端缺少相应回读接口。

MaaEnd CLI 通过轮询异步任务状态响应 Ctrl-C，两个 Agent 不继承终端中断；取消任务并释放输入后才关闭 Agent。

自动化鼠标位移从 0.1.6 起声明为 `relative_delta_mode=win32_scaled_single_frame`：Windows 位移按 MaaEnd `MapNavigator/navi_config.h` 的分辨率比例换算，Legacy 增量在同一帧内可重复读取，但不会延续到下一帧。未被读取的菜单增量会过期，绝对位置和按键更新不会覆盖待消费增量。玩家物理输入保留原有路径与灵敏度。当前客户端水平轴实测约为每单位 0.25°；垂直轴实测响应非线性，滑索的 `RelativeMove` 由 MaaEnd 控制器使用 0.1.7 的只读相机接口进行反馈调整，不在插件中改动玩家鼠标灵敏度；修改游戏镜头设置后仍应重新验证。

## 验证顺序

先确认 `status` 的 `ready` 和 PC 界面，再运行本仓库的 `probe` 并切换到其他窗口检查更新计数。`native_app_active` 用于确认 macOS 宿主是否真正失焦，不能只用 Unity 的 `focused` 判断。接着验证截图、菜单点击、组合键、相对转向与断连释键，最后迁移实际任务。验收范围是同桌面、窗口保持显示且未最小化，允许被其他程序遮挡；隐藏、最小化、其他 Space 和台前调度不作支持承诺。

2026-10-17 实机回读确认鼠标坐标与发送值一致，Shift 按下和释放分别为 true、false。该验证修正了 `il2cpp_runtime_invoke` 的指针参数传递：`InputEvent*` 必须直接放入参数数组，不能再次取地址。模拟框架也使用相同的正确 ABI。这一步仅验证设备状态，未验证实际任务或镜头转向。

0.1.2 补齐 Legacy 链路后，实际 CustomController 在 `native_app_active=false` 时成功点击标题界面的设置，并用 Esc 关闭菜单。用户同时确认真实点击和 Esc 恢复。`legacy_input_reads` 记录游戏调用 Legacy 钩子的次数，不以连接成功或虚拟设备回读代替界面响应验收。

0.1.3 进一步补齐 Cursor 状态与宿主相对鼠标输入，避免悬停坐标更新清掉相对位移。用户确认世界中的镜头、左右键和切出后的系统光标均正常，也确认不发送操作的自动化会话期间可继续手动操作。

0.1.4 将心跳与 Unity 主线程状态读取分开，MaaEnd 同时延长单次 MaaTools 转场截图时限并采用本地 TCP 连接双 Agent。既有 PC 菜单、设置、返回世界和地图入口均已通过。首次采集路线完成传送与定位，但自动转向过快，最终导航失败，未记为采集成功。

转向诊断发现旧的 50 毫秒 Legacy 保留策略会跨帧重复自动化增量；10 单位实际转动 5.6°～8.6°，而 Windows 导航预期约为 0.84°。0.1.5 改为单帧消费后，四次 ±120 单位往返实测约为 ±29.2°～29.9°；0.1.6 加入自动化单位换算。六项 CTest 覆盖单帧消费、过期、回绕、分辨率换算、手动输入不缩放以及原有运行时与输入链路。

0.1.6 使用 Windows 导航的 ±357 单位（1920×1080 下预期约 ±30°），图像模型测得 +30.46°、−29.67°、+29.15°、−29.14°。用户确认手动镜头、左右键与菜单均正常。随后完整通过既有 `AutoCollectRoute6Start`：传送、地图定位、NAVMESH 导航和 8 次“轻红柱状菌”的 OCR 命中及 F 交互均完成，根任务返回 succeeded，结束后 `automation=false`。背包净增加数量未单独核对，其他路线未验收。

0.1.7 增加按签名解析的世界相机只读查询，模拟验证确认查询不会开启自动化会话。用户登上滑索并进入瞄准状态后，MaaEnd 正式反馈控制器完成 30° 俯仰往返，误差小于 0.5°；上限复位后向下 30° 到 59.81°，下限复位后向上 30° 到 −30.46°。MXU 适配版完成连接、实时截图、两轮俯仰任务及中途停止，停止后仍可再次执行。最后关闭 GUI 后 `automation=false`，未残留控制器子进程；该轮未发射或实际乘坐滑索。适配补丁与构建器现已迁入本仓库的 `patches/` 和 `tools/EndPlayDesktop/`；使用方法见根目录 README 与控制器文档。

后续单段滑索实测通过：既有上架组件完成 Alt 点击，正式控制器调整偏航与俯仰后，一次左键发射并滑到约 105 米外的目标架，再以 80 毫秒右键下架。MapLocator 确认坐标从 `(461.52, 880.59)` 变为目标架 `(479.11, 808.75)`，随后地面识别节点成功命中。所有观测帧中宿主均失焦；结束后自动化关闭且输入释放。本轮保持实现不变；自动选索、多跳及重规划未在此单段验证中执行。

## 与原插件的实现对照

| 路径 | 原插件 | EndPlayDesktop |
| --- | --- | --- |
| PC UI | 设置 `Beyond.DeviceInfo` 的平台与输入类型 | 同一游戏接口 |
| 新输入系统 | 创建 Mouse、Keyboard，排入 StateEvent | 同一机制，修正指针参数 ABI 并增加真实设备回读 |
| Legacy 键鼠 | 从 `UnityView.handleCommand:` 定位未导出键盘函数，替换鼠标 icall 缓存 | 0.1.2 补齐；此前仅尝试 `dlsym` 导致这条链路缺失 |
| 世界场景光标状态 | 隐藏光标时向游戏报告已锁定 | 0.1.3 补齐相同语义，恢复镜头与世界场景鼠标按键 |
| 物理输入 | GameController 回调、宿主鼠标位置轮询，抑制 Unity 触屏回调 | 运行时就绪后安装 GameController 回调，额外转发 UIKit 点击与按键 |
| 系统光标 | 包含光标锁定、关联和位置调整 | 仅前台手动操作按游戏请求捕获，失焦释放；后台自动化不操作系统光标 |

## 参考

- [Unity Input System](https://github.com/Unity-Technologies/InputSystem)：事件头、MouseState、Key 枚举和后台行为。
- [PlayTools MaaTools 分支](https://github.com/hguandl/PlayTools/tree/MaaTools)：自定义插件加载和截图协议。
- PC 模式方法签名来自对用户提供客户端与插件的只读检查；本实现不链接或分发原插件。
