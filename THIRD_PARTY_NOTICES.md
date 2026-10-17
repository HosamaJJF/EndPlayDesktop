# 第三方来源 / Third-party sources

EndPlayDesktop 包含针对以下项目的源码补丁及原有上下文，保留各上游作者的版权。EndPlayDesktop includes source patches and their original context for the following projects; copyright remains with the upstream authors.

| 项目 / Project | 来源 / Source | 基线 / Baseline | 许可证 / License |
| --- | --- | --- | --- |
| MaaEnd | <https://github.com/MaaEnd/MaaEnd> | `v2.33.0`, `39a22f9176a2484c38c10d256b8f595d4370f6a9` | AGPL-3.0 |
| MXU | <https://github.com/MistEO/MXU> | `v2.8.0`, `5e923e83b30a102fb78da35c30ee2e1559aea682` | AGPL-3.0 |

完整许可证见 [LICENSE](./LICENSE)。Full license text is provided in [LICENSE](./LICENSE).

MaaFramework Python SDK、NumPy、Pillow、json5 等依赖由包管理器安装，各自沿用原许可证，不把依赖源码和二进制纳入本仓库提交。Dependencies including the MaaFramework Python SDK, NumPy, Pillow, and json5 are installed through the package manager under their own licenses; their sources and binaries are not committed here.

`tests/mock_unity.mm` 是独立编写的测试替身；不包含游戏 UnityFramework、商业游戏资源或 `libUnityDesktopMode.dylib`。`tests/mock_unity.mm` is an independently written test fixture; game UnityFramework, commercial game assets, and `libUnityDesktopMode.dylib` are not included.
