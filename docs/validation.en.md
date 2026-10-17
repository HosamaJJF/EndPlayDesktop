# Local validation record

[中文](./validation.md)

Validated on 2026-10-17 using the original MaaEnd.app `v2.33.0`, Apple Silicon, and EndPlayDesktop `0.1.7`.

## Builds and unit tests

- The plugin was rebuilt; all six CTests and local signature verification passed.
- All 41 controller and patch tests passed in the independent Python environment.
- Official MaaEnd source revision: `39a22f9176a2484c38c10d256b8f595d4370f6a9`; Go Agent controller-type tests and compilation passed.
- MXU source baseline: `5e923e83b30a102fb78da35c30ee2e1559aea682`. This run reused the development executable whose TypeScript, Vite, and Rust builds had passed previously; the default builder produces a release artifact.

## App-copy validation

- Compatibility entries were added for 43 Windows tasks, excluding `LaunchGamePC` and `CloseGamePC`.
- Changes covered 44 interface or task files and 46 controller restrictions. The complete file diff contained 48 entries, additionally including MXU, Go Agent, the patch receipt, and the resource-signature seal.
- Pipelines, recognition assets, C++ Agent, and MaaFramework libraries remained byte-for-byte identical.
- `Info.plist`, all nine original controllers, and main-interface metadata outside the controller list remained unchanged, including version, project address, and update identifiers.
- Strict complete signature verification passed. Reapplication returned `already_applied`; rollback restored every file's original content.
- Backup and restore use `ditto` to retain extended signature attributes on packaged JSON files.

## Original app and interface

The patch was applied to the existing local MaaEnd.app. Its window title remains `MaaEnd v2.33.0`, the top-right label remains `MaaEnd`, and EndPlayDesktop appears beside the original controllers. The original official update-check endpoint returned `code=0` and `version_name=v2.33.0`. No game business task ran in this round, and compatibility entries are not treated as acceptance of every task.
