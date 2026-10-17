from __future__ import annotations

import json
import os
import socket
import stat
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MAX_MESSAGE = 64 * 1024
BUNDLE_ID = "com.hypergryph.endfield"


class BridgeError(RuntimeError):
    """插件协议、会话或游戏输入更新失败。"""


@dataclass(frozen=True)
class Endpoint:
    port: int
    token: str = field(repr=False)

    @classmethod
    def read(cls, path: Path) -> Endpoint:
        """只读取当前用户私有的本地连接描述文件，不向日志暴露令牌。"""
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise BridgeError("连接描述文件必须属于当前用户，且仅当前用户可读写")
            if info.st_size > MAX_MESSAGE:
                raise BridgeError("连接描述文件过大")
            value = json.load(stream)
        if not isinstance(value, dict):
            raise BridgeError("连接描述文件格式错误")
        if value.get("protocol") != 1 or value.get("bundle_id") != BUNDLE_ID or value.get("host") != "127.0.0.1":
            raise BridgeError("连接描述文件的协议、应用或监听地址不匹配")
        port, token = value.get("port"), value.get("token")
        if type(port) is not int or not 1 <= port <= 65535:
            raise BridgeError("连接描述文件端口无效")
        if not isinstance(token, str) or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
            raise BridgeError("连接描述文件令牌无效")
        return cls(port=port, token=token)


def find_endpoint() -> Path:
    """定位终末地容器中的连接描述；多份文件时要求明确指定。"""
    home = Path.home()
    candidates = [
        home / "Library/Containers" / BUNDLE_ID / "Data/Library/Caches/EndPlayDesktop/endpoint.json",
        home / "Library/Caches" / BUNDLE_ID / "EndPlayDesktop/endpoint.json",
        home / "Library/Caches/EndPlayDesktop/endpoint.json",
    ]
    found = [p for p in candidates if p.is_file()]
    if len(found) == 1:
        return found[0]
    if not found:
        raise BridgeError("未发现 EndPlayDesktop 连接描述，请先加载插件，或通过 --endpoint 指定 endpoint.json")
    raise BridgeError("发现多份连接描述，请通过 --endpoint 明确指定")


class BridgeClient:
    """带心跳与输入消费确认的单连接协议客户端。"""

    def __init__(self, endpoint: Path) -> None:
        self._endpoint = endpoint
        self._socket: socket.socket | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._heartbeat: threading.Thread | None = None
        self.last_error: str | None = None
        self._deadline = 0.0

    @property
    def connected(self) -> bool:
        return self._socket is not None and self.last_error is None

    def connect(self) -> dict[str, Any]:
        if self._socket is not None:
            raise BridgeError("连接已建立")
        endpoint = Endpoint.read(self._endpoint)
        self._stop.clear()
        self.last_error = None
        try:
            self._socket = socket.create_connection(("127.0.0.1", endpoint.port), timeout=2.5)
            result = self.request("hello", protocol=1, token=endpoint.token)
        except Exception:
            self.close()
            raise
        self._heartbeat = threading.Thread(target=self._keep_alive, name="EndPlayDesktop-heartbeat", daemon=True)
        self._heartbeat.start()
        return result

    def _receive(self, size: int) -> bytes:
        result = bytearray()
        assert self._socket is not None
        while len(result) < size:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("插件响应超时")
            self._socket.settimeout(remaining)
            part = self._socket.recv(size - len(result))
            if not part:
                raise BridgeError("插件断开连接")
            result.extend(part)
        return bytes(result)

    def request(self, op: str, **fields: Any) -> dict[str, Any]:
        body = json.dumps({"op": op, **fields}, allow_nan=False, separators=(",", ":")).encode()
        if len(body) > MAX_MESSAGE:
            raise BridgeError("输入请求过大")
        with self._lock:
            if self._socket is None:
                raise BridgeError("插件未连接")
            try:
                self._deadline = time.monotonic() + 2.5
                self._socket.settimeout(2.5)
                self._socket.sendall(struct.pack("!I", len(body)) + body)
                size = struct.unpack("!I", self._receive(4))[0]
                if not 0 < size <= MAX_MESSAGE:
                    raise BridgeError("插件响应长度无效")
                result = json.loads(self._receive(size))
                if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                    raise BridgeError("插件响应格式无效")
            except (OSError, ValueError, BridgeError) as exc:
                self.last_error = str(exc)
                self._stop.set()
                self._socket.close()
                self._socket = None
                raise BridgeError(f"EndPlayDesktop 通信失败: {exc}") from exc
        if not result["ok"]:
            raise BridgeError(str(result.get("error", "插件拒绝请求")))
        return result

    def apply(self, op: str, **fields: Any) -> dict[str, Any]:
        """等待 Input System 消费事件，避免同一输入更新内按下又释放。"""
        result = self.request(op, **fields)
        count = result.get("input_update_count")
        if type(count) is not int:
            raise BridgeError("插件未返回输入更新计数")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            current = self.request("status")
            if not current.get("ready") or not current.get("automation"):
                raise BridgeError("游戏输入通道或自动化会话失效")
            if current.get("input_update_count") != count:
                return current
            if self._stop.wait(0.005):
                raise BridgeError("连接已停止")
        # 主线程还能处理请求但游戏不消费输入，也必须结束会话并释键。
        try:
            self.request("end")
        finally:
            self.close()
        raise BridgeError("Unity 输入更新停滞，已结束自动化会话；请检查游戏是否暂停或被最小化")

    def _keep_alive(self) -> None:
        while not self._stop.wait(0.75):
            try:
                self.request("ping")
            except (BridgeError, OSError) as exc:
                self.last_error = str(exc)
                self._stop.set()
                return

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            if self._socket is not None:
                try:
                    self._socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self._socket.close()
                self._socket = None
        if self._heartbeat and self._heartbeat is not threading.current_thread():
            self._heartbeat.join(timeout=3)
        self._heartbeat = None

    def __enter__(self) -> BridgeClient:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
