# Local validation record

[中文](./validation.md)

## 2026-10-30: fixed startup delay and native PlayCover connection behavior

- The launch pretask only opens or reuses the game through the OS and waits for a configurable 0–300 seconds, defaulting to 10. It does not read an address, probe the plugin or MaaTools, destroy an existing controller, or force reconnection. The input defaults to port 1717; saved addresses are retained. Missing saved configuration follows the native configuration-required error, without a 1718 fallback. Cancellation cleanup and launch-only completion handling remain.
- All 74 Python tests, 4 frontend tests, TypeScript checking, Vite and Rust release builds passed, along with clean-source and repeat-preparation validation.
- A 30-second reuse run from 08:45:22 to 08:45:52 retained both game and controller-child PIDs. Native logs contained no controller destruction or connection calls, and the subsequent no-input task passed.
- The requested real cold-start regression used the target app's original two Agents and SwitchTeam for team 01. The game opened at 08:53:42; after 10 seconds, the first connection succeeded and the real task began at 08:53:52. Login succeeded at 08:54:23, the world was entered at 08:54:24, team selection was confirmed at 08:54:38, and the full task succeeded at 08:54:46. No manual game clicks were performed. This real-task result selected the 10-second default instead of 30.
- A fresh profile displayed 1717. With zero delay, its pretask completed at 08:57:38 and normal MXU connection handling reported missing device configuration rather than connecting to 1718.
- In the supplied reference checkout, MaaCore PlayToolsController::start_game returns success directly, and its Mac branch skips the Android startup loop. StartUpTask's doubled task interval and 50 retries govern post-connection login recognition, not a fixed pre-connection startup delay.
- An unsigned official update DMG in the app's download cache prevented test-copy signing; that update cache was deleted with explicit user authorization. Update-service implementation was unchanged, and no release was published.

## 2026-10-30: withdraw immediate address synchronization

- Restore the existing Connect-to-submit workflow and remove immediate input writes, address invalidation flags, and additional locking state. Ten UI, store, and locale files match their pre-experiment versions byte for byte. Existing controller integration, startup readiness, failure handling, cancellation, and game-close compatibility patches remain.
- All 8 frontend regressions, TypeScript checking, frontend and Rust release builds passed. The reduced patch passed clean-source and repeated source preparation checks.
- The test copy's WebUI was disabled; validation used the native desktop UI only. A configuration without `savedDevice` started at 01:18:09, became ready and connected at 01:18:17, and completed a no-input validation task at 01:18:18.
- Editing the address to 1719 alone left the submitted address unset; clicking Connect saved 1719. After confirming no service listened there, connection failed as expected. The startup wait at 01:19:32 used the submitted 1719, and cancellation ended the waiter. Submitting the actual port 1718 then restored successful readiness and connection at 01:20:10 and task completion at 01:20:11. No forwarding service was started, PlayCover settings were unchanged, and no business input was performed.
- Documentation now explains that installation replaces the entire MXU. A newer MXU bundled with MaaEnd requires porting, rebuilding, and validation; task/resource compatibility does not preserve newer MXU features automatically.

## 2026-10-30: connection address follows the input immediately (withdrawn)

The following records cover the withdrawn implementation. The current implementation submits the address on Connect and removes this experiment's additional input state, invalidation, and locking logic.

- The input, startup readiness checks, and controller connection share the instance address state. No save or Connect click is required. Editing invalidates the old connection; starting tasks destroys the old controller and creates one for the current address.
- A separate native GUI configuration without `savedDevice` waited from 00:33:34 to 00:33:42 during cold startup, then connected and completed a no-input validation task. The address field and Connect button were disabled during startup.
- After a successful run on 1718 at 00:37:27, only the input was changed to 1719, without clicking Connect. Both the readiness check and new controller used 1719 at 00:37:58, and the validation task succeeded at 00:37:59. Changing back to 1718 and starting directly also succeeded at 00:38:25. Port 1719 temporarily forwarded over loopback to the game's actual port 1718; PlayCover settings were unchanged.
- Editing no longer triggers the upstream initial auto-reconnect, which could otherwise lock the field after the first character. Starting with an empty address prompts for a MaaTools address before launching the pretask, without falling back to 1718.
- All 10 frontend tests, 73 Python tests, TypeScript checking, frontend and Rust release builds passed. The final patch passed clean-source and repeat-preparation checks. No team-switching, game-closing, or other business tasks were executed, and no release was published.

## 2026-10-29: First connection from a new configuration

The reported configuration had no `savedDevice`. Its launch pretask completed plugin and capture checks between 19:47:44 and 19:47:51, but the following connection stage returned `needConfig`. Startup and connection used different address fallback rules.

- Both stages now share one connection configuration. EndPlayDesktop defaults to `127.0.0.1:1718` without a saved address and retains saved custom addresses. Native PlayCover address behavior is preserved.
- Startup logs show the readiness wait and 90-second timeout while polling actual plugin and capture readiness.
- 8 frontend tests, 73 Python tests, TypeScript checking, frontend/Rust builds, clean-source patching, and repeated source preparation passed.
- A separate GUI configuration contained no `savedDevice` and was never connected manually. It waited from 20:01:33 to 20:01:40, connected automatically, loaded resources, and completed a subsequent no-input probe node at 20:01:41. No team-switch or close task was executed.

## 2026-10-29: Game launch and close tasks

Validated with MaaEnd `v2.36.0-beta.5`, the MXU `v2.8.0` build reference, and local PlayCover Endfield. No release was published.

- 73 Python tests and 9 CTests passed, along with MXU TypeScript checking, frontend build, and Rust release build.
- Dedicated launch/close definitions and a separate `resource_endplaydesktop` attachment were added. Clean MXU source accepts both patch layers; preparing the source repeatedly is idempotent.
- Two real-game cycles passed: launch, controller connection, native MaaFramework StopApp, process exit, and relaunch. Startup checks the current PID, plugin state, and MaaTools capture; controller connection can follow the readiness probe's asynchronous cleanup.
- Endfield's MaaTools TERM request stalled in `NSApplication._shouldTerminate`. Close first requests TERM, then revalidates the Bundle ID, application path, and launch date before sending SIGTERM after a timeout. Kernel process disappearance confirms exit.
- Local patch application, ZIP, and DMG were generated. Bundled-runtime and sidecar protocol checks passed.
- Applying and reapplying to a MaaEnd copy passed full signature verification. Content hashes matched for 2,887 existing Agent, framework, resource, data, configuration, and debug files. Only signature metadata is refreshed for generated records; Mach-O files are skipped.
- The separate-project GUI passed launch-only, repeat execution while connected, cold launch and close, invalid-path abort, cancellation, and resuming after cancellation. Cancellation removed the waiter process and retained the opened game.
- The original MaaEnd installation and task configuration were not replaced; GUI validation uses a separate project copy.

## 2026-10-25: upstream update compatibility in 0.0.3

Validated against a copy of the official MaaEnd `v2.36.0-beta.1` app, without modifying the installed app or operating the game.

- All 52 Python tests and 12 MXU TypeScript tests passed, along with TypeScript checking, Vite, and the Rust release build.
- The payload contains only MXU and its manifest. The build no longer downloads, compiles, or distributes Go Agent.
- With a virtual controller and `PI_CONTROLLER.type=MacOS`, the stock Agent recognized the desktop controller. The same `configure_minimum_price` call succeeded on the stock Agent and reproduced the failure on the old v2.33.0 patched Agent.
- All 2800 Agent, MaaFramework, resource, data, locale, and `Info.plist` files retained identical content hashes. Controller registration changed 45 interface/task files and 47 restrictions.
- Strict deep signature verification passed, reapplying returned `already_applied`, and backup restoration succeeded.
- A simulated legacy patch recovered the exact original Agent from a same-version backup. Missing, wrong-version, and cyclic backups are covered by unit tests.
- App signing changes the executable's raw hash. Reapplication uses its Mach-O build UUID and still verifies the full app signature.

These checks cover parameter compatibility and app integrity, rather than a complete in-game outpost transaction. Major changes to ProjectInterface, the Agent protocol, controller APIs, or the MaaFramework ABI still require compatibility review.

## Historical validation

The `0.1.x` numbers in this document refer to internal builds before publication. The first public version is `0.0.1` and includes these features.

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
