from __future__ import annotations

import plistlib
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from .client import BUNDLE_ID, BridgeError
from .lifecycle import game_bundle, game_process, launch_game, open_game, terminate_process, wait_for_exit


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.now = 0.0
        self.stack.enter_context(patch("tools.EndPlayDesktop.lifecycle.time.monotonic", side_effect=lambda: self.now))
        self.stack.enter_context(patch("tools.EndPlayDesktop.lifecycle.time.sleep", side_effect=self.advance))
        self.bundle = self.stack.enter_context(patch("tools.EndPlayDesktop.lifecycle.game_bundle", return_value=Path("/game.app")))
        self.app = Mock()
        self.app.processIdentifier.return_value = 123
        self.app.isTerminated.return_value = False
        self.alive = self.stack.enter_context(patch("tools.EndPlayDesktop.lifecycle.process_alive", return_value=True))
        self.open = self.stack.enter_context(patch("tools.EndPlayDesktop.lifecycle.open_game", return_value=self.app))

    def advance(self, duration: float) -> None:
        self.now += duration

    def test_launch_only_opens_and_delays_without_contacting_services(self) -> None:
        with patch("tools.EndPlayDesktop.client.find_endpoint", side_effect=AssertionError("no probe")), \
                patch("tools.EndPlayDesktop.client.BridgeClient", side_effect=AssertionError("no bridge")), \
                patch("tools.EndPlayDesktop.capture.MaaToolsCapture", side_effect=AssertionError("no capture")):
            launch_game()
        self.open.assert_called_once_with(Path("/game.app"), 90)
        self.assertEqual(self.now, 10)

    def test_delay_is_configurable_and_zero_skips_wait(self) -> None:
        launch_game(delay=2.5)
        self.assertEqual(self.now, 2.5)
        launch_game(delay=0)
        self.assertEqual(self.now, 2.5)

    def test_invalid_delay_and_open_timeout_fail_before_launch(self) -> None:
        for delay in (-1, 301, float("nan"), float("inf")):
            with self.subTest(delay=delay), self.assertRaisesRegex(ValueError, "等待时间"):
                launch_game(delay=delay)
        for timeout in (0, -1, 301, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, "启动超时"):
                launch_game(timeout=timeout)
        self.open.assert_not_called()

    def test_exit_must_be_observed_and_timeout_is_not_success(self) -> None:
        with self.assertRaisesRegex(BridgeError, "关闭游戏超时"):
            wait_for_exit(self.app, timeout=0.2)
        self.alive.side_effect = [True, False]
        wait_for_exit(self.app)
        self.assertEqual(self.alive.call_args.args, (123,))

    def test_fallback_checks_launch_identity_and_only_sends_sigterm(self) -> None:
        from signal import SIGTERM

        with patch("tools.EndPlayDesktop.lifecycle.game_process", return_value=self.app), \
                patch("tools.EndPlayDesktop.lifecycle.os.kill") as kill:
            terminate_process(self.app)
            kill.assert_called_once_with(123, SIGTERM)
        replacement = Mock()
        replacement.isTerminated.return_value = False
        with patch("tools.EndPlayDesktop.lifecycle.game_process", return_value=replacement), \
                patch("tools.EndPlayDesktop.lifecycle.os.kill") as kill:
            with self.assertRaisesRegex(BridgeError, "身份已变化"):
                terminate_process(self.app)
            kill.assert_not_called()

    def test_app_bundle_identity_is_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "Game.app"
            bundle.mkdir()
            info = bundle / "Info.plist"
            info.write_bytes(plistlib.dumps({"CFBundleIdentifier": BUNDLE_ID}))
            self.assertEqual(game_bundle(str(bundle)), bundle.resolve())
            info.write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.hypergryph.arknights"}))
            with self.assertRaisesRegex(ValueError, "终末地"):
                game_bundle(str(bundle))

    def test_already_running_game_is_reused_and_other_installations_are_rejected(self) -> None:
        appkit = Mock()
        self.app.bundleURL.return_value.path.return_value = "/game.app"
        appkit.NSRunningApplication.runningApplicationsWithBundleIdentifier_.return_value = [self.app]
        with patch.dict(sys.modules, {"AppKit": appkit}):
            self.assertIs(open_game(Path("/game.app"), 90), self.app)
            appkit.NSWorkspace.sharedWorkspace.assert_not_called()
            with self.assertRaisesRegex(BridgeError, "另一个位置"):
                open_game(Path("/other/game.app"), 90)

    def test_pid_reuse_by_another_app_cannot_terminate_it(self) -> None:
        appkit = Mock()
        appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_.return_value.bundleIdentifier.return_value = "other.app"
        with patch.dict(sys.modules, {"AppKit": appkit}):
            with self.assertRaisesRegex(BridgeError, "不是终末地"):
                game_process(123)
            with self.assertRaisesRegex(BridgeError, "进程标识"):
                game_process(None)


if __name__ == "__main__":
    unittest.main()
