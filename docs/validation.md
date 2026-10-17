# 本地验证记录

[English](./validation.en.md)

文中的 `0.1.x` 为公开发布前的内部验证编号；首次公开版本统一为 `0.0.1`，包含这些功能。

2026-10-17，使用原始 MaaEnd.app `v2.33.0`、Apple Silicon 和 EndPlayDesktop `0.1.7` 验证。

## 构建与单元测试

- 插件重新编译，六项 CTest 通过，本地签名校验通过。
- 独立 Python 环境下，41 项控制器与补丁测试通过。
- MaaEnd 官方源码提交为 `39a22f9176a2484c38c10d256b8f595d4370f6a9`；Go Agent 控制器类型测试和编译通过。
- MXU 源码基线为 `5e923e83b30a102fb78da35c30ee2e1559aea682`，本轮复用此前已通过 TypeScript、Vite、Rust 构建的开发版可执行文件；默认构建命令生成 release 产物。

## 包体副本验证

- 43 个 Windows 任务追加兼容标记；`LaunchGamePC` 与 `CloseGamePC` 排除。
- 共修改 44 个接口或任务文件、46 处控制器限制；完整文件差异为 48 项，另含 MXU、Go Agent、补丁收据与资源签名封印。
- Pipeline、识别资源、C++ Agent 与 MaaFramework 库逐字节保持原样。
- `Info.plist`、原有九个控制器及除控制器列表外的主接口元数据保持原样，包括版本、项目地址和更新标识。
- 严格完整签名校验通过；重复应用返回 `already_applied`；回滚后全部文件内容与原包完全一致。
- 备份和恢复使用 `ditto`，保留包内 JSON 的扩展签名属性。

## 原包应用与界面

已应用到本机原 MaaEnd.app，窗口标题仍为 `MaaEnd v2.33.0`，右上角仍为 `MaaEnd`，原控制器旁新增 EndPlayDesktop。原官方更新检测接口返回 `code=0` 与 `version_name=v2.33.0`。本轮不执行游戏业务任务，不将兼容标记视为所有任务验收通过。
