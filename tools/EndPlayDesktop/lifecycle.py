"""Launch the installed PlayCover game, delay, and observe exit without sending input."""
from __future__ import annotations

import math
import logging
import os
import plistlib
import signal
import time
from pathlib import Path
from typing import Any

from .client import BUNDLE_ID, BridgeError


def game_bundle(path: str = "") -> Path:
    bundle = (Path(path).expanduser() if path else
              Path.home() / "Library/Containers/io.playcover.PlayCover/Applications" / f"{BUNDLE_ID}.app")
    bundle = bundle.resolve(strict=True)
    if bundle.suffix != ".app" or plistlib.loads((bundle / "Info.plist").read_bytes()).get("CFBundleIdentifier") != BUNDLE_ID:
        raise ValueError("请选择 PlayCover 安装的终末地应用")
    return bundle


def game_process(pid: int) -> Any:
    from AppKit import NSRunningApplication

    if type(pid) is not int or pid <= 0:
        raise BridgeError("插件未提供有效的游戏进程标识，请重新连接")
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is not None and app.bundleIdentifier() != BUNDLE_ID:
        raise BridgeError("插件记录的进程不是终末地，请重新连接")
    return app


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def open_game(bundle: Path, deadline: float) -> Any:
    from AppKit import NSRunningApplication, NSWorkspace, NSWorkspaceOpenConfiguration
    from Foundation import NSDate, NSRunLoop, NSURL

    running = NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE_ID)
    for app in running:
        if not process_alive(int(app.processIdentifier())):
            continue
        if Path(app.bundleURL().path()).resolve() != bundle:
            raise BridgeError("另一个位置的终末地正在运行，请先退出该应用")
        if not app.isTerminated():
            return app

    result: list[tuple[Any, Any]] = []
    config = NSWorkspaceOpenConfiguration.configuration()
    config.setActivates_(False)
    config.setCreatesNewApplicationInstance_(False)
    config.setEnvironment_({key: value for key, value in os.environ.items()
                            if not key.startswith(("DYLD_", "PYTHON", "_PYI"))})
    NSWorkspace.sharedWorkspace().openApplicationAtURL_configuration_completionHandler_(
        NSURL.fileURLWithPath_(str(bundle)), config, lambda app, error: result.append((app, error)))
    while not result:
        if time.monotonic() >= deadline:
            raise BridgeError("打开游戏超时")
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
    app, error = result[0]
    if error is not None or app is None:
        raise BridgeError(f"无法打开游戏：{error}")
    return app


def launch_game(path: str = "", delay: float = 10, timeout: float = 90) -> None:
    if not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise ValueError("启动超时必须大于 0 且不超过 300 秒")
    if not math.isfinite(delay) or not 0 <= delay <= 300:
        raise ValueError("启动后等待时间必须在 0 到 300 秒之间")
    open_game(game_bundle(path), time.monotonic() + timeout)
    if delay:
        logging.info("游戏已打开，等待 %g 秒", delay)
        time.sleep(delay)
    else:
        logging.info("游戏已打开")


def wait_for_exit(app: Any, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while app is not None:
        # NSRunningApplication state can remain cached on a MaaFramework worker
        # thread. Ask the kernel whether this process still exists.
        if not process_alive(int(app.processIdentifier())):
            return
        if time.monotonic() >= deadline:
            raise BridgeError("关闭游戏超时，应用尚未退出")
        time.sleep(0.1)


def terminate_process(app: Any) -> None:
    pid = int(app.processIdentifier())
    current = game_process(pid)
    if current is None or current.isTerminated():
        return
    if current.bundleURL().path() != app.bundleURL().path() or current.launchDate() != app.launchDate():
        raise BridgeError("游戏进程身份已变化，拒绝终止其他进程")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
