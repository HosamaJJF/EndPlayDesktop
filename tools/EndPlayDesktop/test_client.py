from __future__ import annotations

import json
import socket
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from .client import BridgeClient, BridgeError, Endpoint, MAX_MESSAGE


class ClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "endpoint.json"
        self.path.write_text(json.dumps({"protocol": 1, "bundle_id": "com.hypergryph.endfield",
                                        "host": "127.0.0.1", "port": 17321, "token": "a" * 64}))
        self.path.chmod(0o600)

    def test_private_descriptor_and_redacted_token(self) -> None:
        endpoint = Endpoint.read(self.path)
        self.assertEqual(endpoint.port, 17321)
        self.assertNotIn("a" * 64, repr(endpoint))
        self.path.chmod(0o644)
        with self.assertRaises(BridgeError):
            Endpoint.read(self.path)

    def test_connect_waits_for_previous_probe_to_release_ownership(self) -> None:
        client = BridgeClient(self.path)
        self.addCleanup(client.close)
        with patch("tools.EndPlayDesktop.client.socket.create_connection", side_effect=[Mock(), Mock()]), \
                patch.object(client, "request", side_effect=[BridgeError("another client owns the connection"), {"ready": True}]), \
                patch("tools.EndPlayDesktop.client.time.sleep") as wait:
            self.assertTrue(client.connect()["ready"])
        wait.assert_called_once_with(0.05)

    def test_connect_does_not_retry_authentication_errors(self) -> None:
        client = BridgeClient(self.path)
        with patch("tools.EndPlayDesktop.client.socket.create_connection", return_value=Mock()) as connect, \
                patch.object(client, "request", side_effect=BridgeError("authentication or protocol mismatch")):
            with self.assertRaisesRegex(BridgeError, "authentication"):
                client.connect()
        connect.assert_called_once()
        self.assertFalse(client.connected)

    def test_descriptor_cannot_select_remote_host(self) -> None:
        value = json.loads(self.path.read_text())
        value["host"] = "192.0.2.1"
        self.path.write_text(json.dumps(value))
        with self.assertRaises(BridgeError):
            Endpoint.read(self.path)

    def test_symlink_descriptor_is_rejected(self) -> None:
        link = self.path.with_name("link.json")
        link.symlink_to(self.path)
        with self.assertRaises(OSError):
            Endpoint.read(link)

    def exchange(self, response: bytes) -> BridgeClient:
        client_sock, server_sock = socket.socketpair()
        client = BridgeClient(self.path)
        client._socket = client_sock
        self.addCleanup(client.close)

        def serve() -> None:
            with server_sock:
                server_sock.recv(MAX_MESSAGE)
                # 故意拆分长度与 body，覆盖流协议的分包边界。
                for part in (response[:1], response[1:3], response[3:7], response[7:]):
                    try:
                        server_sock.sendall(part)
                    except BrokenPipeError:
                        # 超长包在长度头处即被拒绝，服务端不应再尝试发送 body。
                        break
        worker = threading.Thread(target=serve)
        worker.start()
        self.addCleanup(worker.join, 2)
        return client

    def test_fragmented_response(self) -> None:
        body = json.dumps({"ok": True, "ready": True}).encode()
        client = self.exchange(struct.pack("!I", len(body)) + body)
        self.assertTrue(client.request("status")["ready"])

    def test_oversize_response_closes_connection(self) -> None:
        client = self.exchange(struct.pack("!I", MAX_MESSAGE + 1))
        with self.assertRaises(BridgeError):
            client.request("status")
        self.assertFalse(client.connected)

    def test_input_ack_waits_for_game_update(self) -> None:
        client = BridgeClient(self.path)
        with patch.object(client, "request", side_effect=[
            {"ok": True, "input_update_count": 9},
            {"ok": True, "ready": True, "automation": True, "input_update_count": 9},
            {"ok": True, "ready": True, "automation": True, "input_update_count": 10},
        ]) as request:
            result = client.apply("key", vk=87, down=True)
        self.assertEqual(result["input_update_count"], 10)
        self.assertEqual(request.call_count, 3)

    def test_stalled_game_ends_session(self) -> None:
        client = BridgeClient(self.path)
        with patch.object(client, "request", return_value={"ok": True, "input_update_count": 9}) as request:
            with patch("tools.EndPlayDesktop.client.time.monotonic", side_effect=[0, 3]):
                with self.assertRaisesRegex(BridgeError, "输入更新停滞"):
                    client.apply("key", vk=87, down=True)
        self.assertEqual(request.call_args.args, ("end",))


if __name__ == "__main__":
    unittest.main()
