from __future__ import annotations

import logging
from functools import wraps
from pathlib import Path
from typing import Callable

import numpy as np
from maa.controller import CustomController

from .client import BUNDLE_ID, BridgeClient, BridgeError
from .capture import MaaToolsCapture
from .pitch import PitchFeedback


logger = logging.getLogger(__name__)


def input_action(action: Callable) -> Callable:
    """阻止异常穿过 MaaFramework 的 C 回调边界，并在失败时结束输入会话。"""
    @wraps(action)
    def guarded(self: EndPlayDesktopController, *args: object, **kwargs: object) -> bool:
        try:
            self.begin_session()
            action(self, *args, **kwargs)
            return True
        except (BridgeError, OSError, ValueError) as exc:
            logger.error("EndPlayDesktop input failed: %s", exc)
            self.close()
            return False
    return guarded


class EndPlayDesktopDevice:
    """MaaTools 负责截图，EndPlayDesktop 负责 Windows VK 与进程内鼠标输入。"""

    def __init__(self, endpoint: Path, maatools_address: str) -> None:
        self.bridge = BridgeClient(endpoint)
        self.capture = MaaToolsCapture(maatools_address)
        self._geometry = (0, 0)
        self._session_active = False
        self._pitch = PitchFeedback()

    def connect(self, start_session: bool = True) -> bool:
        try:
            status = self.bridge.connect()
            if not status.get("ready"):
                raise BridgeError(str(status.get("error", "插件尚未就绪")))
            if status.get("keycode") != "win32_vk":
                raise BridgeError("插件键码模式不兼容")
            if status.get("relative_delta_mode") != "win32_scaled_single_frame":
                raise BridgeError("插件鼠标位移模式不兼容，请安装 EndPlayDesktop 0.1.6 或更新版本")
            self.capture.connect()
            image = self.capture.screencap()
            self._geometry = (image.shape[1], image.shape[0])
            if self._geometry != (status.get("width"), status.get("height")):
                raise BridgeError("MaaTools 截图与 Unity 渲染分辨率不一致，不能可靠映射坐标")
            if start_session:
                self.begin_session()
            return True
        except (BridgeError, OSError, ValueError, RuntimeError) as exc:
            logger.error("EndPlayDesktop connection failed: %s", exc)
            self.close()
            return False

    def connected(self) -> bool:
        return self.bridge.connected

    def begin_session(self) -> None:
        if not self._session_active:
            self.bridge.request("begin")
            self._session_active = True

    def end_session(self) -> None:
        if self.bridge.connected:
            self.bridge.request("end")
        self._session_active = False
        self._pitch = PitchFeedback()

    def request_uuid(self) -> str:
        return "maa.endplaydesktop"

    def get_custom_info(self) -> dict:
        # C++ 使用桌面输入后端；PI_CONTROLLER 使用上游支持的 MacOS 桌面类型。
        return {"backend": "EndPlayDesktop", "layout": "desktop", "keycode": "win32_vk"}

    def screencap(self) -> np.ndarray:
        try:
            # 转场期间 Unity 主线程可能忙于载入；截图由独立的 MaaTools 提供，
            # 不应先排队执行托管状态查询。心跳仍检查连接，输入命令独立检查会话。
            if not self.bridge.connected:
                raise BridgeError("自动化连接已失效")
            image = self.capture.screencap()
            if image is None or image.size == 0:
                raise BridgeError("MaaTools 返回空截图")
            actual = (image.shape[1], image.shape[0])
            if actual != self._geometry:
                raise BridgeError("运行期间游戏分辨率变化，请停止后重新连接")
            return image.copy()
        except (BridgeError, OSError, ValueError, RuntimeError) as exc:
            logger.error("EndPlayDesktop capture failed: %s", exc)
            self.close()
            return np.empty((0, 0, 3), dtype=np.uint8)

    @input_action
    def touch_down(self, contact: int, x: int, y: int, pressure: int) -> None:
        if contact not in (0, 1, 2):
            raise ValueError("desktop contact must be 0:left, 1:right or 2:middle")
        self.bridge.apply("move", x=x, y=y, delta=False)
        self.bridge.apply("button", button=contact, down=True)

    @input_action
    def touch_move(self, contact: int, x: int, y: int, pressure: int) -> None:
        if contact not in (0, 1, 2):
            raise ValueError("unsupported mouse contact")
        self.bridge.apply("move", x=x, y=y, delta=True)

    @input_action
    def touch_up(self, contact: int) -> None:
        self.bridge.apply("button", button=contact, down=False)

    @input_action
    def key_down(self, keycode: int) -> None:
        self.bridge.apply("key", vk=keycode, down=True)

    @input_action
    def key_up(self, keycode: int) -> None:
        self.bridge.apply("key", vk=keycode, down=False)

    @input_action
    def scroll(self, dx: int, dy: int) -> None:
        self.bridge.apply("scroll", dx=dx, dy=dy)

    @input_action
    def relative_move(self, dx: int, dy: int) -> None:
        if dy:
            if dx:
                self.bridge.apply("relative", dx=dx, dy=0)
            self._pitch.turn(self.bridge, self._geometry[1], dy)
        else:
            self.bridge.apply("relative", dx=dx, dy=0)

    def click(self, x: int, y: int) -> bool:
        return self.touch_down(0, x, y, 0) and self.touch_up(0)

    def click_key(self, keycode: int) -> bool:
        return self.key_down(keycode) and self.key_up(keycode)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int) -> bool:
        # 当前仅实现桌面 touch_down/move/up 路径，不冒充支持直接 Swipe 回调。
        logger.error("direct swipe callback is not supported by EndPlayDesktop")
        return False

    def input_text(self, text: str) -> bool:
        logger.error("EndPlayDesktop does not yet support InputText")
        return False

    def start_app(self, intent: str) -> bool:
        return False

    def stop_app(self, intent: str) -> bool:
        if intent != BUNDLE_ID:
            logger.error("仅支持关闭终末地")
            return False
        try:
            from .lifecycle import game_process, terminate_process, wait_for_exit

            app = game_process(self.bridge.pid)
            if app is not None and not app.isTerminated():
                self.end_session()
                self.bridge.close()
                self.capture.terminate()
                try:
                    wait_for_exit(app, timeout=3)
                except BridgeError:
                    logger.warning("游戏未退出，正在重试关闭")
                    terminate_process(app)
                    wait_for_exit(app, timeout=5)
            return True
        except (BridgeError, OSError, ValueError, RuntimeError, ImportError) as exc:
            logger.error("关闭游戏失败：%s", exc)
            return False
        finally:
            self.close()

    def inactive(self) -> bool:
        try:
            self.end_session()
            return True
        except (BridgeError, OSError) as exc:
            logger.error("EndPlayDesktop release failed: %s", exc)
            self.close()
            return False

    def close(self) -> None:
        if self.bridge.connected:
            try:
                self.end_session()
            except (BridgeError, OSError):
                pass
        self._session_active = False
        self._geometry = (0, 0)
        self._pitch = PitchFeedback()
        self.bridge.close()
        self.capture.close()


class EndPlayDesktopController(EndPlayDesktopDevice, CustomController):
    """CLI 的原生 CustomController；MXU sidecar 直接复用纯设备层。"""

    def __init__(self, endpoint: Path, maatools_address: str) -> None:
        EndPlayDesktopDevice.__init__(self, endpoint, maatools_address)
        CustomController.__init__(self)

    def inactive(self) -> bool:
        self.close()
        return True
