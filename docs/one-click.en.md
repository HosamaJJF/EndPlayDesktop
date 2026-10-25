# One-click patch application

[中文](./one-click.md)

Download and extract `EndPlayDesktop-0.0.3-macos-arm64.zip`, or open the matching DMG. For Apple Silicon Macs, the app includes its runtime and prebuilt patch; Python, uv, Go, and Rust are not required.

## Apply the patch

1. Quit MaaEnd completely. The game may remain running.
2. Double-click `EndPlayDesktopPatch.app`.
3. The default target is `/Applications/MaaEnd.app`. Use “选择 MaaEnd…” (Choose MaaEnd) if it is installed elsewhere.
4. Click “应用补丁” (Apply Patch) and wait for completion.
5. Open the original MaaEnd, select EndPlayDesktop, enter the game's actual MaaTools address, and connect.

The app name, MaaEnd version, official update sources, and existing task logic remain unchanged. Windows tasks receive additional compatibility entries, excluding game launch and close. The tool preserves the target app's Go/C++ Agents, MaaFramework, and business resources. Reapply the same tool after ordinary MaaEnd updates; no per-release Agent rebuild is needed. Major protocol or framework ABI changes may still require an updated patch.

Tools through 0.0.2 replaced Go Agent. Migration restores it from a matching unpatched backup. If that backup is missing, reinstall the current official MaaEnd app once, then apply this tool. Keep the task configuration.

## Game plugin

The distribution also includes `libEndPlayDesktop.dylib`. Load it through PlayCover's Endfield custom plugin settings and keep MaaTools enabled. Restart the game after replacing its plugin. An existing installation of the current plugin does not need replacement. See the plugin documentation in the source archive.

## Backup and restore

Backups, controller runtimes, and logs live under `~/Library/Application Support/EndPlayDesktop/`, without depending on the download or development source directory. After applying, you may quit the tool, move the download, or eject the DMG.

To restore, quit MaaEnd, open the tool, choose the corresponding MaaEnd app, and click “恢复备份” (Restore Backup), then confirm. This restores the state preceding the last patch application. After a MaaEnd update, open the tool and apply the patch again.

## Source and building

The distribution includes `EndPlayDesktop-source.zip` and its license. Developers can run from the source directory:

```bash
uv sync --group bundle
uv run --group bundle python -m tools.EndPlayDesktop.build_app
```

Generate `.cache/payloads/desktop/` and `build/libEndPlayDesktop.dylib` before building. Outputs under `dist/` include the double-clickable app, ZIP, and DMG. The current test package is ad-hoc signed locally and is not Apple-notarized.
