from __future__ import annotations

import io
import json
import logging
import struct
import sys
from typing import BinaryIO

from PIL import Image

from .client import BridgeError
from .controller import EndPlayDesktopDevice


MAX_HEADER = 64 * 1024
MAX_IMAGE = 32 * 1024 * 1024
INPUT_ARGUMENTS = {
    "touch_down": 4, "touch_move": 4, "touch_up": 1,
    "key_down": 1, "key_up": 1, "relative_move": 2, "scroll": 2,
}


def read_exact(stream: BinaryIO, size: int) -> bytes:
    value = bytearray()
    while len(value) < size:
        part = stream.read(size - len(value))
        if not part:
            raise EOFError("MXU controller channel closed")
        value.extend(part)
    return bytes(value)


def dispatch(device: EndPlayDesktopDevice, request: dict) -> tuple[object, bytes]:
    op = request.get("op")
    if not isinstance(op, str):
        raise ValueError("controller operation must be a string")
    arguments = request.get("args", [])
    if not isinstance(arguments, list):
        raise ValueError("controller arguments must be an array")
    if op in INPUT_ARGUMENTS:
        if len(arguments) != INPUT_ARGUMENTS[op] or any(type(value) is not int for value in arguments):
            raise ValueError("invalid controller input arguments")
        return getattr(device, op)(*arguments), b""
    if arguments:
        raise ValueError("unexpected controller arguments")
    if op == "connect":
        return device.connected() or device.connect(start_session=False), b""
    if op == "connected":
        return device.connected(), b""
    if op == "inactive":
        return device.inactive(), b""
    if op == "screencap":
        image = device.screencap()
        if image.size == 0:
            raise BridgeError("empty game screenshot")
        output = io.BytesIO()
        Image.fromarray(image[:, :, ::-1]).save(output, format="PNG", compress_level=1)
        payload = output.getvalue()
        if len(payload) > MAX_IMAGE:
            raise BridgeError("encoded screenshot exceeds controller channel limit")
        return True, payload
    if op == "close":
        device.close()
        return True, b""
    raise ValueError("unsupported controller operation")


def serve(device: EndPlayDesktopDevice, source: BinaryIO, output: BinaryIO) -> None:
    """仅通过 MXU 继承的私有双向通道服务，不另开监听端口。"""
    try:
        while True:
            size = struct.unpack("!I", read_exact(source, 4))[0]
            if not 0 < size <= MAX_HEADER:
                raise ValueError("invalid controller request length")
            request = json.loads(read_exact(source, size))
            if not isinstance(request, dict):
                raise ValueError("controller request must be an object")
            try:
                result, payload = dispatch(device, request)
                response = {"ok": True, "result": result, "payload_size": len(payload)}
            except (BridgeError, OSError, ValueError) as exc:
                device.close()
                payload = b""
                response = {"ok": False, "error": str(exc), "payload_size": 0}
            body = json.dumps(response, separators=(",", ":"), allow_nan=False).encode()
            output.write(struct.pack("!I", len(body)) + body + payload)
            output.flush()
            if request.get("op") == "close":
                return
    except EOFError:
        pass
    finally:
        device.close()


def main(device: EndPlayDesktopDevice) -> int:
    try:
        serve(device, sys.stdin.buffer, sys.stdout.buffer)
        return 0
    except (OSError, ValueError) as exc:
        logging.error("EndPlayDesktop sidecar stopped: %s", exc)
        return 1
