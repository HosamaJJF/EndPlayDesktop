from __future__ import annotations

import socket
import struct
import time

import numpy as np

from .client import BUNDLE_ID, BridgeError

CAPTURE_TIMEOUT = 15.0


class MaaToolsCapture:
    """使用 MaaTools 截图及退出协议，所有网络读写都有超时，不转发触摸。"""

    def __init__(self, address: str) -> None:
        host, separator, port = address.rpartition(":")
        if not separator or host not in ("localhost", "127.0.0.1") or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError("MaaTools 地址必须是本机 localhost:端口 或 127.0.0.1:端口")
        self._port = int(port)
        self._socket: socket.socket | None = None
        self.width = self.height = 0
        self._deadline = 0.0

    def _receive(self, count: int) -> bytes:
        if self._socket is None:
            raise BridgeError("MaaTools 未连接")
        data = bytearray()
        while len(data) < count:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("MaaTools 截图响应超时")
            self._socket.settimeout(remaining)
            part = self._socket.recv(count - len(data))
            if not part:
                raise BridgeError("MaaTools 断开连接")
            data.extend(part)
        return bytes(data)

    def _command(self, command: bytes, timeout: float = 2.5) -> None:
        if self._socket is None:
            raise BridgeError("MaaTools 未连接")
        self._deadline = time.monotonic() + timeout
        self._socket.settimeout(timeout)
        self._socket.sendall(struct.pack("!H", len(command)) + command)

    def connect(self) -> None:
        self.close()
        try:
            self._socket = socket.create_connection(("127.0.0.1", self._port), timeout=2.5)
            self._deadline = time.monotonic() + 2.5
            self._socket.sendall(b"MAA\0")
            if self._receive(4) != b"OKAY":
                raise BridgeError("MaaTools 握手失败")
            self._command(b"VERN")
            if struct.unpack("!I", self._receive(4))[0] < 4:
                raise BridgeError("需要 MaaTools 协议 v4，以验证截图来自终末地")
            self._command(b"BNDL")
            size = struct.unpack("!I", self._receive(4))[0]
            if not 0 < size <= 4096 or self._receive(size).decode("utf-8") != BUNDLE_ID:
                raise BridgeError("MaaTools 连接的应用不是终末地")
            self._command(b"SIZE")
            self.width, self.height = struct.unpack("!HH", self._receive(4))
            if self.width <= 0 or self.height <= 0 or self.width * self.height * 4 > 256 * 1024 * 1024:
                raise BridgeError("MaaTools 截图尺寸无效")
        except Exception:
            self.close()
            raise

    def screencap(self) -> np.ndarray:
        try:
            # 游戏转场时 MaaTools 的单帧响应也可能阻塞；等待本次请求完成，
            # 不重发截图命令，也不延长输入命令的取消时限。
            self._command(b"SCRN", timeout=CAPTURE_TIMEOUT)
            size = struct.unpack("!I", self._receive(4))[0]
            if size == 0:
                raise BridgeError("MaaTools 返回空截图，请检查 PlayTools 的窗口捕获日志；此时不能运行任务")
            if size != self.width * self.height * 4:
                raise BridgeError("MaaTools 截图长度或分辨率变化，请重新连接")
            rgba = np.frombuffer(self._receive(size), dtype=np.uint8).reshape(self.height, self.width, 4)
            # MaaFramework 的识别接口接收 BGR；MaaTools SCRN 返回 RGBA。
            return rgba[:, :, 2::-1].copy()
        except Exception:
            self.close()
            raise

    def terminate(self) -> None:
        # Recheck the bundle on a fresh connection before sending a command that
        # exits the process. TERM has no response; process observation confirms exit.
        try:
            self.connect()
            self._command(b"TERM")
        except Exception:
            self.close()
            raise
        # Keep the channel alive until the caller observes exit. Closing it here
        # can cancel MaaTools' asynchronous command handler before TERM runs.

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
