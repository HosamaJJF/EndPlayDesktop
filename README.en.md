# EndPlayDesktop

[中文](./README.md)

Injects PC UI changes and in-process keyboard/mouse input into Arknights: Endfield running in PlayCover, and patches MaaEnd to add an EndPlayDesktop controller so Windows-controller tasks can run in PlayCover. This project is maintained independently of MaaEnd and MXU. It requires the community [PlayCover fork](https://github.com/hguandl/PlayCover/releases) with MaaTool support.

The plugin injects changes into the game. Do not use this project if you are concerned about the risks. This project accepts no responsibility for any resulting loss or penalty affecting your game account.

## Project structure

| Path | Contents |
| --- | --- |
| `src/`, `CMakeLists.txt` | Game plugin sources and build configuration |
| `tools/EndPlayDesktop/`, `patch.py` | Controller, capture, and patch tools |
| `patches/` | MXU controller source patch |
| `packaging/` | Packaging configuration for the one-click patch app |
| `tests/`, `docs/` | Tests and detailed documentation |

## Installation

Install the community PlayCover fork above, Endfield, and MaaEnd first, then enable the MaaTool port in PlayCover.

1. Go to this repository's **Releases** and download the patch `.dmg` and `libEndPlayDesktop.dylib`.
2. Quit the game completely. In PlayCover, right-click Endfield, open **设置 → 杂项** (Settings → Miscellaneous), and add the downloaded `.dylib` as a custom plugin. Remove `libUnityDesktopMode.dylib` first if it is installed.
3. **Turn off “启用键盘映射布局” (Enable Keymapping Layout)**, keep MaaTool enabled, and restart the game.
4. Quit MaaEnd completely. Open `EndPlayDesktopPatch.app` from the `.dmg`, select your installed `MaaEnd.app`, and click “应用补丁” (Apply Patch).
5. Reopen MaaEnd, choose the **EndPlayDesktop** controller, enter the game's MaaTools address, and connect.

The patch preserves MaaEnd's existing features and marks Windows tasks and upstream PlayCover launch/close tasks as compatible with EndPlayDesktop. Compatibility labels do not mean every task has been tested. Launch and close reuse MaaEnd's existing tasks without adding dedicated tasks or Pipelines. The target app keeps its own Go/C++ Agents, MaaFramework, and business resources. Reapply the same tool after ordinary MaaEnd updates without rebuilding Agents for each release. Keep the game window neither minimized nor hidden; it can run in the background without taking over the keyboard or mouse.

## Build from source

Requires Xcode, CMake, Ninja, Git, Node.js 22, pnpm, Rust, Tauri, and uv. Run these commands from the repository root:

```bash
uv sync --group bundle

# Build the game plugin
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build

# Build the MaaEnd patch; the first run downloads upstream sources and dependencies
uv run python patch.py build --app /Applications/MaaEnd.app --mxu-source .cache/sources/MXU

# Package the controller patch for reuse across MaaEnd updates
uv run --group bundle python -m tools.EndPlayDesktop.build_app --payload .cache/payloads/desktop
```

The plugin is written to `build/libEndPlayDesktop.dylib`; the patch application is placed in `dist/`.

This project is licensed under [AGPL-3.0](./LICENSE). See the [third-party notices](./THIRD_PARTY_NOTICES.md) for attribution.
