# One-click patch application

[中文](./one-click.md)

Download and extract `EndPlayDesktop-0.0.4-macos-arm64.zip`, or open the matching DMG. For Apple Silicon Macs, the app includes its runtime and prebuilt patch; Python, uv, Go, and Rust are not required.

## Apply the patch

1. Quit MaaEnd completely. The game may remain running.
2. Double-click `EndPlayDesktopPatch.app`.
3. The default target is `/Applications/MaaEnd.app`. Use “选择 MaaEnd…” (Choose MaaEnd) if it is installed elsewhere.
4. Click “应用补丁” (Apply Patch) and wait for completion.
5. Open the original MaaEnd, select EndPlayDesktop, enter the game's actual MaaTools address, and click Connect to submit it. New configurations display `127.0.0.1:1717`, matching native PlayCover; existing saved addresses are retained.

The app name, MaaEnd version, official update sources, and existing task logic remain unchanged. Windows tasks receive additional compatibility entries; game launch and close use dedicated tasks supplied by the patch. The tool preserves the target app's Go/C++ Agents, MaaFramework, and business resources. Reapply the same tool after ordinary MaaEnd updates; no per-release Agent rebuild is needed. Major protocol or framework ABI changes may still require an updated patch.

Tools through 0.0.2 replaced Go Agent. Migration restores it from a matching unpatched backup. If that backup is missing, reinstall the current official MaaEnd app once, then apply this tool. Keep the task configuration.

The tool replaces the entire MXU executable, currently built against MXU v2.8.0. If MaaEnd includes a newer MXU, port the patch, rebuild, and validate it first; an old patch does not automatically preserve that MXU version's features and fixes.

## Launching and closing the game

With EndPlayDesktop selected, add the launch and close tasks. Launch runs before the controller connects, regardless of list order. Place close after business tasks. A launch-only run still follows normal connection handling and requires a saved device address.

Leave the application path empty to use `com.hypergryph.endfield.app` in the current user's PlayCover container, or enter the full `.app` path. The launch pretask only opens or reuses the game, then waits for the configured startup delay: 10 seconds by default, adjustable from 0 to 300. It does not read the connection address, probe the plugin, MaaTools, or screenshots, or release/rebuild controller connections. Increase the delay if needed; the following normal MXU connection stage determines readiness. Existing tasks handle login and entering the game.

Address submission, the default input value, auto-reconnect, valid connection reuse, and old connection cleanup follow native PlayCover rules. Editing alone does not submit an address. Without a saved address, starting tasks reports missing device configuration rather than falling back to 1718. Cancelling launch ends its delay process and leaves the game running. Close still releases input and requests exit through MaaTools, falling back to SIGTERM after checking process identity if necessary, and confirms process exit.

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
