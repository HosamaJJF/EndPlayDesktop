# EndPlayDesktop

[中文](./README.md)

Provides PC UI and in-process keyboard/mouse input for Arknights: Endfield in PlayCover, with a local patch that adds an EndPlayDesktop controller to MaaEnd. This project is maintained independently, with no current upstream submission to MaaEnd or MXU.

> This README is a draft framework. The maintainer will add installation screenshots, compatibility versions, and release notes.

## Project contents

| Path | Contents |
| --- | --- |
| `src/`, `CMakeLists.txt` | PlayCover custom plugin sources |
| `tools/EndPlayDesktop/` | Controller, MaaTools capture, patch builder and installer |
| `patches/` | Source patches for MXU and MaaEnd Go Agent, build reference versions |
| `patch.py` | MaaEnd.app patch entry point |
| `tests/` | Simulated plugin tests |
| `docs/` | Plugin protocol and controller development notes |

## Prerequisites

Requires an Apple Silicon Mac, Xcode with the Mac Catalyst SDK, PlayCover, and MaaTools. Builds also require CMake, Ninja, Git, Go, Node.js 22, pnpm, Rust, `cargo tauri`, and uv.

```bash
uv sync
```

To add: verified macOS, PlayCover, MaaTools, and game versions, plus tool installation steps.

## Build and load the game plugin

```bash
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build
ctest --test-dir build --output-on-failure
```

In PlayCover's Endfield custom plugin settings, replace the old `libUnityDesktopMode.dylib` with `build/libEndPlayDesktop.dylib`, keep MaaTools enabled, and restart the game. See the [plugin documentation](./docs/plugin.en.md).

To add: PlayCover settings screenshots, a PC UI example, and how to find the MaaTools port.

## Patch MaaEnd.app

Quit MaaEnd and keep the original installation package. The following uses `/Applications/MaaEnd.app`:

```bash
# Build a patch matching the installed version; the first build downloads official sources and dependencies
uv run python patch.py build --app /Applications/MaaEnd.app

# Preview affected files and controller availability
uv run python patch.py plan --app /Applications/MaaEnd.app

# Back up the original app, apply the patch, and sign it locally
uv run python patch.py apply --app /Applications/MaaEnd.app
```

The patch retains the app name, icon, title, project address, and original controllers, adding an independent EndPlayDesktop address connection option. MaaEnd's version number, official update sources, and update logic stay unchanged. Tasks and options restricted to Windows controllers receive an additional compatibility entry, except game launch `LaunchGamePC` and game close `CloseGamePC`. Tasks without controller restrictions are already selectable. Compatibility entries do not establish successful testing of every task.

Reopen the original MaaEnd.app, choose EndPlayDesktop, and enter the game's actual MaaTools address. Keep the game window shown and unminimized; other applications may cover it, and manual player input remains available.

To add: controller settings screenshots, recommended game settings, and manual test results.

## MaaEnd updates and rollback

After a MaaEnd update overwrites the patch, repeat `build`, `plan`, and `apply`. Resource compatibility entries are generated from the new package, and Go Agent is built from the matching official source. Future MaaEnd versions are attempted by default, without a version or client-fingerprint compatibility allowlist; adjustments are made when actual patching problems appear. MXU `v2.8.0` is the current default build reference, not a MaaEnd compatibility ceiling.

`apply` prints the backup directory. Quit MaaEnd, then use that path to restore the complete original app:

```bash
uv run python patch.py restore --app /Applications/MaaEnd.app --backup /absolute/path/to/backup
```

`backups/`, `.cache/`, and build outputs are not committed. The patch depends on this repository's Python environment; after moving the repository, reapply it to update runtime paths. MaaEnd user configuration stays under the original client's management.

## Development and known limits

```bash
uv run python -m unittest discover -s tools/EndPlayDesktop -t . -p 'test_*.py'
uv run python -m tools.EndPlayDesktop status
```

See the [controller development notes](./docs/controller.en.md). Game start/stop and text input are unimplemented. The Maa Pipeline Support extension does not yet support this controller and is not modified by this project. Capture with hidden/minimized windows or across Spaces is not guaranteed.

To add: issue template, compatibility matrix, and release workflow.

## Sources and license

This repository uses [AGPL-3.0](./LICENSE) and retains attribution to MaaEnd and MXU; see [third-party notices](./THIRD_PARTY_NOTICES.md). Game files, the original third-party plugin, and its binaries are not included.
