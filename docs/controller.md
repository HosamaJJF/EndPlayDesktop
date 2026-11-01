# 控制器与包体补丁

[English](./controller.en.md)

文中的 `0.1.x` 为公开发布前的内部验证编号；首次公开版本统一为 `0.0.1`，包含这些功能。

本仓库维护控制器、MaaTools 截图客户端和 MaaEnd.app 补丁。游戏内插件在同一仓库独立编译，详见[插件文档](./plugin.md)。

## 责任边界

`tools/EndPlayDesktop/patch.py` 动态修改原包接口和导入任务文件中的控制器限制；`patches/mxu.patch` 与 `patches/mxu/controller.rs` 提供独立控制器类型、地址表单、配置持久化和创建分支；Agent 通过现有的 `MacOS` 桌面类型识别控制器，无需修改或重新编译。

不改写上游 Pipeline 节点、游戏资源、业务算法、原控制器设置、MaaEnd 版本字段或更新源。游戏启动与关闭复用上游 PlayCover 任务，仅追加控制器兼容标记。MXU 的更新服务源码不在补丁内。MaaEnd 仍检查自己的官方更新；更新覆盖本地支持后需要重新应用补丁。

## 构建与应用

普通用户可使用内置运行环境的[一键补丁工具](./one-click.md)。命令行操作流程见根目录 [README](../README.md)。构建仅生成 MXU 控制器客户端，不检出 MaaEnd 或编译 Agent；MXU 默认使用 `patches/versions.json` 记录的构建参考。未来版本默认尝试兼容，不以已知版本、原始二进制哈希或客户端指纹拦截。实际补丁不能应用时再处理；原生驱动已有其他编辑时不覆盖本地改动。

构建产物位于 `.cache/payloads/desktop/`，只包含 MXU 和哈希清单，可供不同 MaaEnd 版本复用。Go/C++ Agent、MaaFramework 库、Pipeline 与业务数据始终取自目标应用。应用前校验补丁产物完整性，不把目标包版本或原始二进制哈希作为兼容限制。维护者可通过 `build --mxu-source /path/to/MXU --mxu-binary /path/to/mxu` 复用已有客户端；此选项由维护者保证二进制来源。

`apply` 在临时副本中修改并签名，成功后替换原包，完整原包备份至 `backups/apps/`。重复应用同一补丁不重复注册控制器。`restore` 恢复备份原包；它不修改 MXU 正常管理的用户配置目录。补丁收据位于 `Contents/Resources/EndPlayDesktop/receipt.json`，用于识别补丁和关联备份。

## 上游更新与旧版迁移

补丁动态读取目标 MaaEnd 的任务与选项限制，保留其 Agent 和业务资源；普通任务、算法与数据更新通常可重新应用同一工具。安装仍会替换整个 MXU 可执行文件，当前构建参考为 MXU v2.8.0。如果 MaaEnd 携带新版 MXU，应用旧补丁不会自动保留新版 MXU 的功能与修复，应将补丁迁移到新版源码并重新构建验证。ProjectInterface、Agent 协议、控制器接口或 MaaFramework ABI 变化时，也需重新评估兼容性。

0.0.2 及更早工具会覆盖 Go Agent。新工具检测到旧收据时，只从同版本且未经补丁修改的原包备份恢复官方 Agent；支持沿多次补丁的备份链查找。缺少备份或版本不符时，在改动应用前停止，并提示重新安装当前版本的官方 MaaEnd 后再应用。不得继续保留已降级的 Agent，也不得从其他版本的备份中恢复。

## 控制器与任务范围

EndPlayDesktop 使用 Windows VK 和 PC 基础资源，不加载 `resource_adb`、`resource_playcover` 或 `MacOSKeyMap.json`。界面和持久化配置中的控制器类型保持 `EndPlayDesktop`；只在传给 Agent 的 `PI_CONTROLLER.type` 中映射成上游已支持的 `MacOS`，名称保持 `EndPlayDesktop`，C++ 导航沿用桌面输入后端。此映射不会加载 macOS 键码或资源覆盖层，也不会触发 Win32 注册表读取。CLI 使用相同约定。

补丁根据 `type=Win32` 查出实际控制器名称，在相关任务及选项的限制列表中追加 EndPlayDesktop；不依赖完整的静态任务清单。另根据 `type=PlayCover` 为 `LaunchGamePlayCover`、`CloseGamePlayCover` 及其选项追加相同标记，不扩展其他仅支持 PlayCover 的任务。`LaunchGamePC` 与 `CloseGamePC` 及其选项始终排除，其他已有控制器限制和选项默认值保留。兼容标记不代表所有任务均已适配或测试。

启动使用上游 `tasks/pretasks/LaunchGamePlayCover.json` 和目标包自己的 Go Agent，保留原有执行参数、路径及等待选项、校验和本地化。关闭使用上游 `tasks/CloseGamePlayCover.json` 及 PC 基础资源中的同名 StopApp 节点。补丁不再创建任务或附加资源，也不再为旧任务添加 MXU 执行特判。重新应用时移除旧版生成的 `tasks/EndPlayDesktop.json`、其导入及 `resource_endplaydesktop/pipeline/lifecycle.json`；构建时自动撤销源码中仍可完整反向应用的旧生命周期补丁，历史差异仅保留在 `patches/legacy/` 用于清理。

需要安装已包含这两个 PlayCover 任务的 MaaEnd。已有任务列表中的旧 EndPlayDesktop 启动、关闭任务需替换为上游 PlayCover 对应任务。EndPlayDesktop 的地址默认显示 1717，提交与复用规则和原生 PlayCover 一致；没有保存地址时不再自动回退到 1718。关闭仍由控制器校验应用和启动身份、释放输入、请求退出并确认进程消失，随后清理连接。

命令行应用补丁时，接口中的 Python 路径指向本仓库 `.venv/bin/python`，项目路径指向本仓库根目录。二者以绝对路径写入目标包，不写入 Git 跟踪文件。不得把 Python 虚拟环境符号链接解析成基础解释器；移动仓库后重新应用补丁。一键工具将运行环境安装到用户的 Application Support 目录，使用独立的控制器启动程序，不依赖本仓库或 `.venv`。

## 输入、截图与清理

截图由 MaaTools v4 `SCRN` 提供，并校验游戏 Bundle ID。Rust 驱动通过继承的私有双向通道调用 Python；两个 Agent 使用本地 TCP。连接与预览不开始输入会话，首次输入才开始；任务停止或完成时释键并恢复后台设置，保留连接。进程退出通过 EOF 清理子进程。

保持游戏窗口显示且未最小化，可被其他程序遮挡。自动化不激活窗口或捕获系统光标；前台玩家输入仍可介入。空帧、输入更新停滞和能力不匹配均失败并清理，不以更新计数单独证明输入已被游戏消费。

插件 0.1.6 起声明 `relative_delta_mode=win32_scaled_single_frame`，避免相对位移跨帧重放。0.1.7 的只读相机接口支持滑索俯仰反馈：按实际俯仰接近目标，误差 0.5° 内完成，5 秒内未收敛则失败；不修改玩家鼠标灵敏度。文本输入尚未实现；游戏启动使用上游 PlayCover 预任务，关闭使用 StopApp → MaaTools TERM，退出等待超时后对已验证的游戏进程发送 SIGTERM。

## 已验证范围

既有原型已验证手动键鼠共存、菜单与地图输入、AutoCollectRoute6，以及一次滑索上架、俯仰、发射、乘坐和下架。它们不等同于所有 Windows 任务或完整多跳滑索规划验收。测试替身与单元测试不能替代实机验证。

当前 Maa Pipeline Support 扩展没有此控制器类型的表单和创建分支，不能仅靠本地配置启用；本仓库不修改该扩展。调试可使用正常 MaaEnd.app 或 `tools.EndPlayDesktop run <entry> --override /path/to/override.json`。CLI 不自动读取 GUI 中保存的任务选项。
