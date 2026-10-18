# EndPlayDesktop

[中文](./plugin.md)

The `0.1.x` numbers in this document refer to internal builds before publication. The first public version is `0.0.1` and includes these features.

A PlayCover plugin for Endfield PC UI and in-process input. This repository maintains the game-side dylib, the controller in `tools/EndPlayDesktop/`, and the MaaEnd.app patch.

## Current scope

- Starts only in `com.hypergryph.endfield`. Resolves exported IL2CPP APIs and managed method signatures without depending on the previous plugin or fixed client addresses.
- Switches the game's `Beyond.DeviceInfo` platform and input type and creates virtual Keyboard and Mouse devices in Unity Input System.
- Provides Windows VK, mouse buttons, absolute position, relative movement, and scrolling. Receives foreground GameController keyboard/mouse input and UIKit touch, key, and hover events both when idle and during automation. Physical scrolling prefers this application's macOS window events, with GameController as a fallback.
- Temporarily enables background updates and IgnoreFocus during automation without manual takeover or pause switching. Player and automation holds are tracked separately; a key stays pressed while either source holds it. Session end, disconnect, or heartbeat timeout releases only automation input and restores settings; focus loss releases only player input.
- Also forwards keyboard and mouse buttons to Legacy Input and supplies mouse position, scrolling, and `MouseAxis1/MouseAxis2`. Bounded ARM64 pattern parsing within the loaded image locates the unexported `UnitySetKeyState` and icall caches, replacing only data pointers; incompatible signatures stop initialization. Text input and Metal capture are not implemented yet.
- Preserves the game's `Cursor.visible` and lock semantics. Manual relative movement in the world comes from this application's mouse events; the host pointer is captured only when the game is foreground and requests locking, and released immediately on focus loss. Background automation neither captures the system pointer nor activates the window.

This is a prototype for device validation. A successful build and simulated IL2CPP tests do not establish compatibility with the game's PC UI, camera controls, background execution, or every Windows Pipeline.

## Build

Requires an Apple Silicon Mac, Xcode with the Mac Catalyst SDK, CMake, and Ninja.

```bash
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build
ctest --test-dir build --output-on-failure
codesign --verify --strict build/libEndPlayDesktop.dylib
```

The output is `build/libEndPlayDesktop.dylib`, targeting arm64 Mac Catalyst with automatic local ad-hoc signing. The simulated UnityFramework under `build/fixtures/` is for tests only and must not be installed into the game.

## Load and connect

1. Fully exit the game. Remove `libUnityDesktopMode.dylib` from Endfield's custom plugin list in PlayCover, then add this project's `libEndPlayDesktop.dylib`.
2. Keep MaaTools enabled and start the game from PlayCover. The plugin does not modify PlayTools or copy itself into the game directory.
3. The plugin writes its listening address and random token to `EndPlayDesktop/endpoint.json` in the application's cache directory. The usual path is `~/Library/Containers/com.hypergryph.endfield/Data/Library/Caches/EndPlayDesktop/endpoint.json`; the authoritative path is logged as `[EndPlayDesktop] connection descriptor`.
4. From the EndPlayDesktop repository, run `uv run python -m tools.EndPlayDesktop status`. If discovery fails, add `--endpoint /absolute/path/endpoint.json` before `status`.

If the previous plugin is also loaded, this plugin disables its own input and reports a conflict. The connection file is private to the current user, and the tools do not print its token.

## Local protocol

The server binds only IPv4 loopback on a random port. Each frame contains a 4-byte big-endian JSON length followed by UTF-8 JSON, up to 64 KiB. The first frame must be `hello` with `protocol: 1` and the descriptor's `token`. Only one authenticated client may own the connection at a time.

| op | Fields | Meaning |
| --- | --- | --- |
| `status` | None | Read readiness, resolution, input update count, and device state on the game main thread |
| `ping` | None | Return `ok=true` on the socket thread to check connection liveness without reading game state |
| `camera` | None | Since 0.1.7, read world-camera pitch, yaw, and FOV without creating an input session |
| `begin` | None | Start automation and save/change background settings while preserving foreground manual input |
| `end` | None | Release automation-held input and restore background settings |
| `key` | `vk`, `down` | Press/release a Windows VK |
| `move` | `x`, `y`, `delta` | Raw game screenshot coordinates; `delta` selects position-derived movement |
| `button` | `button`, `down` | 0 left, 1 right, 2 middle, 3/4 auxiliary buttons |
| `relative` | `dx`, `dy` | Windows desktop displacement converted using render resolution, with downward-positive input Y |
| `scroll` | `dx`, `dy` | Windows wheel increments, 120 per tick; Input System receives these units and Legacy receives ticks |
| `release` | None | Release keys and buttons held by automation |

Input requires an active `begin` / `end` session. A request making no progress for 3 seconds disconnects and schedules main-thread cleanup. If the game main thread stalls, unexecuted requests are cancelled and cleanup runs when the main thread resumes. The response's `input_update_count` comes from Unity Input System, and the controller waits for it to advance before returning, but the count alone does not prove event consumption. `device_state` reads mouse position, the left button, and the most recent key directly from actual Unity controls; `available=false` means the client lacks these readback APIs.

The MaaEnd CLI polls asynchronous task status to handle Ctrl-C. Both Agents are isolated from terminal interrupts and are closed after task cancellation and input release.

Since 0.1.6, automated mouse movement declares `relative_delta_mode=win32_scaled_single_frame`: Windows displacement is converted using the resolution ratios in MaaEnd's `MapNavigator/navi_config.h`. Legacy increments can be read repeatedly within one frame but do not persist into the next. Unread menu increments expire, and absolute position or button updates do not overwrite pending increments. Physical input retains its existing path and sensitivity. The current client's horizontal axis measured about 0.25° per unit. The vertical axis has a nonlinear response. For zipline `RelativeMove`, the MaaEnd controller uses the read-only camera API added in 0.1.7 for feedback without changing physical mouse sensitivity in the plugin. Camera-setting changes still require validation.

### Scroll units and consumption

The scroll boundary uses Windows units, with 120 units per tick. Physical input converts wheel ticks to these units; automation's `scroll` command supplies them directly. Input System receives 120 per tick, Legacy `mouseScrollDelta` receives 1, and both `MouseAxis3` and `Mouse ScrollWheel` names through `GetAxis` / `GetAxisRaw` receive 0.1.

Physical scrolling prefers local `NSEvent` input. When the monitor is installed, GameController scrolling is not forwarded, preventing duplicate input. Ordinary wheel events round nonzero fractional Cocoa deltas away from zero to wheel ticks. Precise trackpad input preserves fractions, initially mapping 10 points to one tick; this ratio still requires device tuning. The horizontal axis is converted to Windows direction, while the vertical axis follows the macOS event direction. If local monitoring cannot be installed, GameController callback values are treated as wheel ticks.

When the world requests pointer locking, vertical precise-trackpad input converts accumulated distance into whole ticks, initially at 40 points per tick, retaining the remainder for subsequent events. Long swipes can emit multiple ticks within the same gesture and reverse direction; there is no per-gesture step limit. Finger lift or cancellation clears fractional remainder, and vertical momentum is discarded. Original precise host events in this mode are consumed so UIKit cannot deliver unfiltered scrolling as well. Precise devices without gesture phases clear remainder after a 200-millisecond idle gap; focus loss clears it too. Continuous menu scrolling and inertia, ordinary mouse wheels, and automation retain their existing conversion. `world_trackpad_scroll_mode=distance_detents` and `world_trackpad_points_per_tick=40` identify this policy and ratio; actual candidate-selection sensitivity still requires in-game acceptance testing.

Legacy scrolling accumulates per frame. All readers in the same frame see the same value, which does not replay on the following frame. Events arriving after a frame's first read wait until the next frame; stale unread input expires. Position and button events do not clear pending scroll input. Player and automation input accumulate independently: focus loss clears only player scrolling, while session end clears only automation scrolling.

The `status` fields `scroll_units_per_tick=120` and `legacy_scroll_mode=single_frame` identify this behavior; `native_scroll_events` counts accepted nonzero physical scroll events. The build, eight CTests, and signature verification pass. On 2026-10-18, the user confirmed improved map zoom and friend-list scrolling, followed by good world-interaction candidate selection after switching to accumulated-distance detents. This feedback does not establish acceptance for every game screen or automation task.

## Validation order

Check `status` readiness and the PC UI, then run this repository's `probe` and switch to another window to inspect update progress. Use `native_app_active` to confirm that the macOS host actually lost focus; Unity's `focused` alone is insufficient. Next verify screenshots, menu clicks, modifier combinations, relative camera movement, and disconnect release before trying real tasks. Acceptance targets a shown, unminimized window on the same desktop, possibly occluded by other applications; hidden or minimized windows, other Spaces, and Stage Manager are not promised.

On 2026-10-17, actual device readback matched the supplied mouse coordinates and reported true/false for Shift press/release. This validation corrected pointer argument passing in `il2cpp_runtime_invoke`: `InputEvent*` must be placed directly in the argument array without taking its address again. The simulated framework now uses the same correct ABI. That check validated device state rather than real tasks or camera turning.

After 0.1.2 restored the Legacy path, the actual CustomController opened the title screen's settings and closed them with Esc while `native_app_active=false`. The user also confirmed that physical clicks and Esc worked again. `legacy_input_reads` counts calls from the game to the Legacy hooks; connectivity and virtual-device readback do not replace verification of UI responses.

Version 0.1.3 additionally restored Cursor state and host relative mouse input, preventing hover coordinate updates from clearing relative movement. The user confirmed that camera movement, world mouse buttons, and the system pointer after switching applications all worked, including manual input during an automation session that sent no actions.

Version 0.1.4 separates heartbeats from Unity main-thread status reads. MaaEnd also extends the single MaaTools loading-frame deadline and uses local TCP for both Agents. Existing PC Pipelines for menus, settings, returning to the world, and opening the map passed. The first collection route completed teleportation and localization but turned too quickly and eventually failed navigation; it does not count as successful collection.

Turning diagnostics found that the old 50-millisecond Legacy hold policy replayed automated increments across frames: 10 units turned 5.6°–8.6°, whereas Windows navigation expected about 0.84°. After 0.1.5 changed to single-frame consumption, four ±120-unit measurements produced approximately ±29.2°–29.9°. Version 0.1.6 adds automated unit conversion. Six CTests cover single-frame consumption, expiry, rollover, resolution conversion, unchanged physical input scaling, and the existing runtime and input paths.

With 0.1.6, Windows navigation input of ±357 units (expected to turn about ±30° at 1920×1080) produced image-model estimates of +30.46°, −29.67°, +29.15°, and −29.14°. The user confirmed normal manual camera input, mouse buttons, and menus. The existing `AutoCollectRoute6Start` then passed completely: teleportation, map localization, NAVMESH navigation, and 8 OCR matches for “轻红柱状菌” followed by F interactions completed. The root task returned succeeded and the session ended with `automation=false`. Net inventory gains were not checked separately; other routes remain unverified.

Version 0.1.7 adds signature-resolved, read-only world-camera queries, with a simulated check that queries do not start automation. After the user mounted a zipline and entered aim mode, the production MaaEnd feedback controller completed a 30° pitch round trip within 0.5° error. Upper reset followed by 30° downward reached 59.81°; lower reset followed by 30° upward reached −30.46°. The MXU adapter passed connection, live capture, two pitch-task pairs, and cancellation followed by another task. GUI exit left `automation=false` and no controller child process. The zipline was neither fired nor ridden in that run. Adapter patches and builders now live in this repository under `patches/` and `tools/EndPlayDesktop/`; see the root README and controller documentation.

A subsequent single-hop ride check passed: the existing mounting component performed an Alt-click, the production controller adjusted yaw and pitch, one left click launched a ride to the destination tower approximately 105 meters away, and an 80-millisecond right-button press dismounted. MapLocator confirmed movement from `(461.52, 880.59)` to destination tower `(479.11, 808.75)`, followed by a successful ground recognition node. The host remained inactive in every observation frame; automation ended with inputs released. The implementation stayed unchanged. Automatic tower selection, multi-hop planning, and replanning were not exercised by this single-hop check.

## Comparison with the original plugin

| Path | Original plugin | EndPlayDesktop |
| --- | --- | --- |
| PC UI | Sets the platform and input type in `Beyond.DeviceInfo` | Uses the same game APIs |
| New input system | Creates Mouse and Keyboard devices and queues StateEvent input | Uses the same mechanism with corrected pointer ABI and actual device readback |
| Legacy input | Locates the unexported keyboard function from `UnityView.handleCommand:` and replaces mouse icall caches | Restored in 0.1.2; the earlier `dlsym` attempt left this path missing |
| World cursor state | Reports a locked cursor to the game when hidden | Restored the same semantics in 0.1.3 for camera input and world mouse buttons |
| Physical input | GameController callbacks, host pointer polling, and suppressed Unity touch callbacks | Installs GameController callbacks after runtime readiness and additionally forwards UIKit touch/key events |
| System cursor | Includes cursor locking, association, and repositioning | Captures only for requested foreground manual input and releases on focus loss; background automation does not manipulate the system pointer |

## References

- [Unity Input System](https://github.com/Unity-Technologies/InputSystem): event headers, MouseState, Key enum, and background behavior.
- [PlayTools MaaTools branch](https://github.com/hguandl/PlayTools/tree/MaaTools): custom plugin loading and screenshot protocol.
- [Apple scrollingDeltaY](https://developer.apple.com/documentation/appkit/nsevent/scrollingdeltay): ordinary versus precise scroll units; [SDL Cocoa mouse implementation](https://github.com/libsdl-org/SDL/blob/main/src/video/cocoa/SDL_cocoamouse.m): reference for rounding ordinary wheel input and the initial precise-scroll ratio.
- PC mode method signatures come from read-only inspection of the supplied client and plugin; this implementation neither links nor distributes the previous plugin.
