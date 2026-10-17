from __future__ import annotations

import socket
import struct
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from .capture import MaaToolsCapture
from .client import BridgeError


class CaptureTests(unittest.TestCase):
    def fake_server(self, bundle: bytes = b"com.hypergryph.endfield", empty_frame: bool = False) -> tuple[MaaToolsCapture, socket.socket]:
        client, server = socket.socketpair()
        self.addCleanup(client.close)

        def read(size: int) -> bytes:
            result = bytearray()
            while len(result) < size:
                part = server.recv(size - len(result))
                if not part:
                    raise EOFError
                result.extend(part)
            return bytes(result)

        def command(expected: bytes) -> None:
            length = struct.unpack("!H", read(2))[0]
            if read(length) != expected:
                raise RuntimeError("unexpected MaaTools command")

        def serve() -> None:
            try:
                with server:
                    if read(4) != b"MAA\0":
                        return
                    server.sendall(b"OKAY")
                    command(b"VERN")
                    server.sendall(struct.pack("!I", 4))
                    command(b"BNDL")
                    server.sendall(struct.pack("!I", len(bundle)) + bundle)
                    command(b"SIZE")
                    server.sendall(struct.pack("!HH", 2, 1))
                    command(b"SCRN")
                    rgba = b"" if empty_frame else bytes([255, 0, 0, 255, 0, 255, 0, 255])
                    server.sendall(struct.pack("!I", len(rgba)) + rgba)
            except (EOFError, BrokenPipeError):
                pass

        worker = threading.Thread(target=serve)
        worker.start()
        self.addCleanup(worker.join, 3)
        capture = MaaToolsCapture("127.0.0.1:1717")
        self.addCleanup(capture.close)
        return capture, client

    def test_capture_checks_bundle_and_converts_rgba_to_bgr(self) -> None:
        capture, sock = self.fake_server()
        with patch("tools.EndPlayDesktop.capture.socket.create_connection", return_value=sock):
            capture.connect()
        image = capture.screencap()
        np.testing.assert_array_equal(image, np.array([[[0, 0, 255], [0, 255, 0]]], dtype=np.uint8))
        self.assertTrue(image.flags.c_contiguous)

    def test_wrong_application_is_rejected(self) -> None:
        capture, sock = self.fake_server(b"com.hypergryph.arknights")
        with patch("tools.EndPlayDesktop.capture.socket.create_connection", return_value=sock):
            with self.assertRaisesRegex(BridgeError, "不是终末地"):
                capture.connect()
        self.assertIsNone(capture._socket)

    def test_remote_capture_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MaaToolsCapture("192.0.2.1:1717")

    def test_empty_frame_reports_capture_failure_and_closes(self) -> None:
        capture, sock = self.fake_server(empty_frame=True)
        with patch("tools.EndPlayDesktop.capture.socket.create_connection", return_value=sock):
            capture.connect()
        with self.assertRaisesRegex(BridgeError, "返回空截图"):
            capture.screencap()
        self.assertIsNone(capture._socket)

    def test_loading_frame_can_arrive_after_the_control_command_timeout(self) -> None:
        capture = MaaToolsCapture("127.0.0.1:1717")
        capture.width, capture.height = 2, 1
        capture._socket = Mock()
        rgba = bytes([255, 0, 0, 255, 0, 255, 0, 255])
        capture._socket.recv.side_effect = [struct.pack("!I", len(rgba)), rgba]
        with patch("tools.EndPlayDesktop.capture.time.monotonic", side_effect=[100.0, 103.0, 108.0]):
            self.assertEqual(capture.screencap().shape, (1, 2, 3))
        capture._socket.sendall.assert_called_once_with(b"\x00\x04SCRN")
        self.assertEqual(capture._socket.settimeout.call_args.args, (7.0,))


if __name__ == "__main__":
    unittest.main()
