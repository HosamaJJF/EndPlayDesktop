# 控制器与包体补丁

[English](./controller.en.md)

本仓库维护控制器、MaaTools 截图客户端和 MaaEnd.app 补丁。游戏内插件在同一仓库独立编译，详见[插件文档](./plugin.md)。

## 责任边界

`tools/EndPlayDesktop/patch.py` 动态修改原包接口和导入任务文件中的控制器限制；`patches/mxu.patch` 与 `patches/mxu/controller.rs` 提供独立控制器类型、地址表单、配置持久化和创建分支；`patches/maaend-agent.patch` 仅增加 Go Agent 对 EndPlayDesktop 桌面类型的识别及显示。

不改写 Pipeline 节点、游戏资源、业务算法、原控制器设置、MaaEnd 版本字段或更新源。MXU 的更新服务源码不在补丁内。MaaEnd 仍检查自己的官方更新；更新覆盖本地支持后需要重新应用补丁。

## 构建与应用

操作流程见根目录 [README](../README.md)。构建时按包体版本检出 MaaEnd 官方标签，并核对原 Go Agent 内嵌的 Git 提交；MXU 固定在 `patches/versions.json` 的基线。补丁不能应用或原生驱动已有其他编辑时停止，不覆盖未知改动。

构建产物位于 `.cache/payloads/<MaaEnd版本>/`，包含 MXU、对应版本 Go Agent 和哈希清单。应用前核对包体版本、原始二进制哈希和补丁产物哈希。维护者可通过 `build --mxu-source /path/to/MXU --mxu-binary /path/to/mxu` 复用从已核对源码构建的客户端；此选项由维护者保证二进制来源。

`apply` 在临时副本中修改并签名，成功后替换原包，完整原包备份至 `backups/apps/`。重复应用同一补丁不重复注册控制器。`restore` 恢复备份原包；它不修改 MXU 正常管理的用户配置目录。补丁收据位于 `Contents/Resources/EndPlayDesktop/receipt.json`，用于识别补丁和关联备份。

## 控制器与任务范围

EndPlayDesktop 使用 Windows VK 和 PC 基础资源，不加载 `resource_adb`、`resource_playcover` 或 `MacOSKeyMap.json`。`PI_CONTROLLER.type` 保持 `EndPlayDesktop`；Go Agent 将其归一化为桌面类型，C++ 导航沿用桌面输入后端。

补丁根据 `type=Win32` 查出实际控制器名称，在相关任务及选项的限制列表中追加 EndPlayDesktop；不依赖完整的静态任务清单。`LaunchGamePC` 与 `CloseGamePC` 及其选项始终排除，其他已有控制器限制和选项默认值保留。兼容标记不代表所有任务均已适配或测试。

接口中的 Python 路径指向本仓库 `.venv/bin/python`，项目路径指向本仓库根目录。二者以绝对路径写入目标包，不写入 Git 跟踪文件。不得把 Python 虚拟环境符号链接解析成基础解释器；移动仓库后重新应用补丁。

## 输入、截图与清理

截图由 MaaTools v4 `SCRN` 提供，并校验游戏 Bundle ID。Rust 驱动通过继承的私有双向通道调用 Python；两个 Agent 使用本地 TCP。连接与预览不开始输入会话，首次输入才开始；任务停止或完成时释键并恢复后台设置，保留连接。进程退出通过 EOF 清理子进程。

保持游戏窗口显示且未最小化，可被其他程序遮挡。自动化不激活窗口或捕获系统光标；前台玩家输入仍可介入。空帧、输入更新停滞和能力不匹配均失败并清理，不以更新计数单独证明输入已被游戏消费。

插件 0.1.6 起声明 `relative_delta_mode=win32_scaled_single_frame`，避免相对位移跨帧重放。0.1.7 的只读相机接口支持滑索俯仰反馈：按实际俯仰接近目标，误差 0.5° 内完成，5 秒内未收敛则失败；不修改玩家鼠标灵敏度。文本输入和游戏启停尚未实现。

## 已验证范围

既有原型已验证手动键鼠共存、菜单与地图输入、AutoCollectRoute6，以及一次滑索上架、俯仰、发射、乘坐和下架。它们不等同于所有 Windows 任务或完整多跳滑索规划验收。测试替身与单元测试不能替代实机验证。

当前 Maa Pipeline Support 扩展没有此控制器类型的表单和创建分支，不能仅靠本地配置启用；本仓库不修改该扩展。调试可使用正常 MaaEnd.app 或 `tools.EndPlayDesktop run <entry> --override /path/to/override.json`。CLI 不自动读取 GUI 中保存的任务选项。
