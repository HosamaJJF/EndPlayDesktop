# 本地验证记录

[English](./validation.en.md)

## 2026-10-25：0.0.3 上游更新兼容

使用官方 MaaEnd `v2.36.0-beta.1` 原包副本验证，未修改已安装应用，也未操作游戏。

- 52 项 Python 测试、12 项 MXU TypeScript 测试通过；TypeScript 检查、Vite 和 Rust release 构建通过。
- 补丁产物只含 MXU 与清单，打包流程不再下载、编译或分发 Go Agent。
- 虚拟控制器使用 `PI_CONTROLLER.type=MacOS`，官方 Agent 正确识别为桌面类型。相同的 `configure_minimum_price` 参数调用在官方 Agent 上成功，在旧 v2.33.0 补丁 Agent 上复现失败。
- 应用前后 2800 个 Agent、MaaFramework、资源、数据、本地化文件及 `Info.plist` 的内容哈希一致；修改 45 个接口/任务文件、47 处控制器限制。
- 严格完整签名校验通过；重复应用返回 `already_applied`；恢复备份成功。
- 模拟旧版补丁覆盖 Agent 后，从同版本原包备份恢复成功，Agent 与原包逐字节一致；缺少备份、备份版本不符及循环备份路径的拒绝分支有单元测试覆盖。
- 重新签名会改变主程序原始哈希，重复应用按 Mach-O 构建 UUID 判断，并继续校验完整签名。

以上验证覆盖参数兼容与包体完整性，不等同于完整游戏据点交易流程验收。ProjectInterface、Agent 协议、控制器 API 或 MaaFramework ABI 大改时仍需重新评估兼容性。

## 历史验证

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
