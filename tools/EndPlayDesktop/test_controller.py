from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from .client import BUNDLE_ID, BridgeError
from .controller import EndPlayDesktopController, EndPlayDesktopDevice


class ControllerTests(unittest.TestCase):
    def controller(self, shape: tuple[int, int, int] = (720, 1280, 3)) -> EndPlayDesktopController:
        def base_init(instance: EndPlayDesktopController) -> None:
            # 本组测试只验证控制器边界，不创建原生 MaaFramework 对象或连接真实游戏。
            instance._handle = None
            instance._own = False

        with patch("tools.EndPlayDesktop.controller.CustomController.__init__", base_init):
            controller = EndPlayDesktopController(Path("unused"), "127.0.0.1:1717")
        controller.bridge = Mock()
        controller.bridge.connected = True
        controller.bridge.connect.return_value = {
            "ready": True, "width": 1280, "height": 720, "keycode": "win32_vk",
            "relative_delta_mode": "win32_scaled_single_frame",
        }
        controller.capture = Mock()
        controller.capture.screencap.return_value = np.zeros(shape, dtype=np.uint8)
        self.addCleanup(controller.close)
        return controller

    def test_raw_windows_key_is_not_converted_twice(self) -> None:
        controller = self.controller()
        self.assertTrue(controller.connect())
        self.assertTrue(controller.key_down(87))
        controller.bridge.apply.assert_called_with("key", vk=87, down=True)

    def test_persistent_device_can_resume_after_inactive_without_reconnecting_capture(self) -> None:
        controller = self.controller()
        self.assertTrue(controller.connect(start_session=False))
        controller.bridge.request.assert_not_called()
        self.assertTrue(controller.key_down(87))
        self.assertTrue(EndPlayDesktopDevice.inactive(controller))
        self.assertTrue(controller.key_down(65))
        self.assertEqual([c.args[0] for c in controller.bridge.request.call_args_list], ["begin", "end", "begin"])
        controller.capture.close.assert_not_called()

    def test_mismatched_render_and_capture_resolution_fails(self) -> None:
        controller = self.controller((1080, 1920, 3))
        with self.assertLogs("tools.EndPlayDesktop.controller", level="ERROR"):
            self.assertFalse(controller.connect())
        controller.bridge.close.assert_called()

    def test_legacy_timed_delta_plugin_is_rejected_before_input(self) -> None:
        controller = self.controller()
        controller.bridge.connect.return_value.pop("relative_delta_mode")
        with self.assertLogs("tools.EndPlayDesktop.controller", level="ERROR"):
            self.assertFalse(controller.connect())
        controller.bridge.request.assert_called_with("end")
        controller.bridge.apply.assert_not_called()
        controller.capture.connect.assert_not_called()

    def test_capture_timeout_ends_session(self) -> None:
        controller = self.controller()
        self.assertTrue(controller.connect())
        controller.bridge.request.return_value = {"ready": True, "automation": True, "width": 1280, "height": 720}
        controller.capture.screencap.side_effect = TimeoutError("simulated capture timeout")
        with self.assertLogs("tools.EndPlayDesktop.controller", level="ERROR"):
            self.assertEqual(controller.screencap().size, 0)
        controller.bridge.request.assert_called_with("end")
        controller.bridge.close.assert_called()

    def test_capture_does_not_depend_on_unity_main_thread_during_loading(self) -> None:
        controller = self.controller()
        self.assertTrue(controller.connect())
        controller.bridge.request.reset_mock()
        controller.bridge.request.side_effect = BridgeError("game main thread did not respond")
        self.assertEqual(controller.screencap().shape, (720, 1280, 3))
        controller.bridge.request.assert_not_called()

    def test_capture_stops_after_heartbeat_disconnect(self) -> None:
        controller = self.controller()
        self.assertTrue(controller.connect())
        controller.capture.screencap.reset_mock()
        controller.bridge.connected = False
        with self.assertLogs("tools.EndPlayDesktop.controller", level="ERROR"):
            self.assertEqual(controller.screencap().size, 0)
        controller.capture.screencap.assert_not_called()

    def test_input_failure_releases_session(self) -> None:
        controller = self.controller()
        controller.bridge.apply.side_effect = BridgeError("simulated input failure")
        with self.assertLogs("tools.EndPlayDesktop.controller", level="ERROR"):
            self.assertFalse(controller.key_up(87))
        controller.bridge.request.assert_called_with("end")

    def test_stop_releases_input_before_term_and_cleans_up_for_reconnect(self) -> None:
        controller = self.controller()
        controller.bridge.pid = 123
        app = Mock()
        app.isTerminated.return_value = False
        calls = Mock()
        calls.attach_mock(controller.bridge.request, "request")
        calls.attach_mock(controller.capture.terminate, "terminate")
        with patch("tools.EndPlayDesktop.lifecycle.game_process", return_value=app), \
                patch("tools.EndPlayDesktop.lifecycle.wait_for_exit") as wait:
            self.assertTrue(controller.stop_app(BUNDLE_ID))
        self.assertEqual(calls.mock_calls[0].args, ("end",))
        self.assertEqual(calls.mock_calls[1], unittest.mock.call.terminate())
        wait.assert_called_once_with(app, timeout=3)
        controller.bridge.close.assert_called()
        controller.capture.close.assert_called()
        self.assertEqual(controller._geometry, (0, 0))
        self.assertFalse(controller._session_active)
        self.assertTrue(controller.connect(start_session=False))

    def test_stop_rejects_other_apps_and_does_not_claim_success_on_exit_timeout(self) -> None:
        controller = self.controller()
        with self.assertLogs("tools.EndPlayDesktop.controller", level="ERROR"):
            self.assertFalse(controller.stop_app("com.hypergryph.arknights"))
        controller.capture.terminate.assert_not_called()
        app = Mock()
        app.isTerminated.return_value = False
        with patch("tools.EndPlayDesktop.lifecycle.game_process", return_value=app), \
                patch("tools.EndPlayDesktop.lifecycle.terminate_process"), \
                patch("tools.EndPlayDesktop.lifecycle.wait_for_exit", side_effect=BridgeError("exit timeout")), \
                self.assertLogs("tools.EndPlayDesktop.controller", level="ERROR"):
            self.assertFalse(controller.stop_app(BUNDLE_ID))
        controller.bridge.close.assert_called()

    def test_stop_falls_back_only_after_term_was_sent_and_confirms_exit(self) -> None:
        controller = self.controller()
        app = Mock()
        app.isTerminated.return_value = False
        with patch("tools.EndPlayDesktop.lifecycle.game_process", return_value=app), \
                patch("tools.EndPlayDesktop.lifecycle.wait_for_exit", side_effect=[BridgeError("timeout"), None]) as wait, \
                patch("tools.EndPlayDesktop.lifecycle.terminate_process") as terminate, \
                self.assertLogs("tools.EndPlayDesktop.controller", level="WARNING"):
            self.assertTrue(controller.stop_app(BUNDLE_ID))
        controller.capture.terminate.assert_called_once()
        terminate.assert_called_once_with(app)
        self.assertEqual(wait.call_count, 2)


if __name__ == "__main__":
    unittest.main()
