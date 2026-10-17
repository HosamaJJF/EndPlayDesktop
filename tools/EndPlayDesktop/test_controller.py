from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from .client import BridgeError
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


if __name__ == "__main__":
    unittest.main()
