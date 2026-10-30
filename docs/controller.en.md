# Controller and app patch

[中文](./controller.md)

The `0.1.x` numbers in this document refer to internal builds before publication. The first public version is `0.0.1` and includes these features.

This repository maintains the controller, MaaTools capture client, and MaaEnd.app patch. The game plugin is built separately in the same repository; see the [plugin documentation](./plugin.en.md).

## Responsibilities

`tools/EndPlayDesktop/patch.py` updates controller restrictions in the original app interface and imported task files. `patches/mxu.patch`, `patches/mxu-lifecycle.patch`, and `patches/mxu/controller.rs` provide a separate controller type, address form, persisted configuration, and creation branch. Agents recognize the controller through their existing `MacOS` desktop kind, without modification or recompilation.

Upstream Pipeline nodes, game resources, business algorithms, original controller settings, MaaEnd version fields, and update sources are not rewritten. Dedicated task definitions and controller-attached resources provide game launch and close. MXU update-service sources are outside the patch. MaaEnd continues checking its own official updates; reapply the patch after an update overwrites local support.

## Building and applying

For normal use, choose the [one-click patch tool](./one-click.en.md) with its bundled runtime. See the root [README](../README.en.md) for CLI commands. Builds only produce the MXU controller client, without checking out MaaEnd or compiling Agents. MXU defaults to the build reference in `patches/versions.json`. Future versions are attempted by default, without blocking on known-version lists, original executable hashes, or client fingerprints. Actual patch-application failures are handled when encountered; existing edits to the native driver are not overwritten.

Outputs under `.cache/payloads/desktop/` contain only MXU and a hash manifest and can be reused across MaaEnd releases. Go/C++ Agents, MaaFramework libraries, Pipelines, and business data come from the target app. Installation verifies payload integrity, without using the target version or original executable hashes as compatibility restrictions. Maintainers can reuse an existing client through `build --mxu-source /path/to/MXU --mxu-binary /path/to/mxu`; maintainers are responsible for the binary's provenance with this option.

`apply` modifies and signs a temporary copy before replacing the app, backing up the complete original under `backups/apps/`. Reapplying the same patch does not duplicate controller registration. `restore` restores the backup without changing the user configuration directory managed by normal MXU. A receipt at `Contents/Resources/EndPlayDesktop/receipt.json` identifies the patch and associated backup.

## Upstream updates and migration

The patch discovers restrictions in the target MaaEnd's tasks and options and preserves its Agents and business resources. Ordinary task, algorithm, and data updates can usually reuse the same tool. Installation still replaces the entire MXU executable, currently built against MXU v2.8.0. If MaaEnd includes a newer MXU, reapplying an old patch does not automatically preserve its features and fixes; port the patch to that source version, rebuild, and validate it. Changes to ProjectInterface, the Agent protocol, controller APIs, or the MaaFramework ABI also require compatibility review.

Tools through 0.0.2 replaced Go Agent. When a legacy receipt is found, the new tool restores the official Agent only from an unpatched backup of the same MaaEnd version, following earlier backup receipts if necessary. If no suitable backup exists, installation stops before modifying the app and asks for a fresh official installation of the current MaaEnd version. It never retains the downgraded Agent or restores one from another release.

## Controller and task scope

EndPlayDesktop uses Windows VK codes and PC base resources, without loading `resource_adb`, `resource_playcover`, or `MacOSKeyMap.json`. The interface and saved controller type remain `EndPlayDesktop`. Only `PI_CONTROLLER.type` passed to Agents maps to the supported `MacOS` desktop kind; the name stays `EndPlayDesktop`. C++ navigation keeps its desktop backend. This mapping neither loads macOS keycode/resource overlays nor enables Win32 registry reads. The CLI uses the same convention.

The patch discovers controller names from `type=Win32` and appends EndPlayDesktop to matching task and option restriction lists, without a complete static task inventory. `LaunchGamePC`, `CloseGamePC`, and their options remain excluded. Other restrictions and option defaults are retained. Compatibility entries do not establish adaptation or testing of every task.

Lifecycle entries are declared in `tasks/EndPlayDesktop.json`; the close node lives in the separate `resource_endplaydesktop` attachment. Launch opens the game through the OS and waits for a configurable delay (10 seconds by default). It does not probe the plugin or capture service, pass an address, or force controller teardown/reconnection. The default input is port 1717; address submission and connection reuse follow native PlayCover, without a port-1718 fallback when no address is saved. Cancellation ends only the startup waiter. Close still verifies application identity, releases input, requests exit, confirms process termination, and clears the connection.

When applying through the CLI, the interface Python path points to this repository's `.venv/bin/python`, with the project path pointing to its root. Absolute paths are generated in the target app and not stored in tracked Git files. Do not resolve the virtual-environment Python symlink to its base interpreter; reapply the patch after moving the repository. The one-click tool installs its runtime in the user Application Support directory and uses a standalone controller launcher, without depending on this repository or `.venv`.

## Input, capture, and cleanup

Capture uses MaaTools v4 `SCRN` and verifies the game Bundle ID. The Rust driver calls Python through an inherited private bidirectional channel; both Agents use local TCP. Connection and preview do not start an input session; the first input does. Completion or cancellation releases inputs and restores background settings while retaining the connection. Process exit cleans up child processes through EOF.

Keep the game window shown and unminimized; other applications may cover it. Automation does not activate the window or capture the system pointer, and foreground manual player input remains available. Empty frames, stalled input updates, and incompatible capabilities fail with cleanup. Update counts alone do not prove game consumption.

Since 0.1.6, the plugin declares `relative_delta_mode=win32_scaled_single_frame` to avoid replaying relative movement across frames. The read-only camera API in 0.1.7 supports zipline pitch feedback, converging from actual pitch readings within 0.5° or failing after five seconds. Physical mouse sensitivity is unchanged. Text input remains unimplemented. A dedicated pretask launches the game; StopApp sends MaaTools TERM, with SIGTERM to a verified game process if the exit wait times out.

## Validated scope

The preceding prototype validated manual input coexistence, menus and map input, AutoCollectRoute6, and one zipline mounting, pitch adjustment, launch, ride, and dismount. These checks do not validate every Windows task or full multi-hop zipline planning. Fixtures and unit tests do not replace device validation.

The installed Maa Pipeline Support extension lacks a form and creation branch for this controller, so local configuration alone cannot enable it; this repository does not modify that extension. Use normal MaaEnd.app or `tools.EndPlayDesktop run <entry> --override /path/to/override.json` for debugging. The CLI does not automatically read task options saved in the GUI.
