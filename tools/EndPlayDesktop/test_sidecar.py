from __future__ import annotations

import io
import json
import struct
import unittest
from unittest.mock import Mock

import numpy as np
from PIL import Image

from .sidecar import MAX_HEADER, dispatch, read_exact, serve


def packet(value: dict) -> bytes:
    body = json.dumps(value).encode()
    return struct.pack("!I", len(body)) + body


class FragmentedInput(io.BytesIO):
    def read(self, size: int = -1) -> bytes:
        return super().read(min(size, 1))


class SidecarTests(unittest.TestCase):
    def test_preview_uses_png_without_changing_color_and_closes_on_eof(self) -> None:
        device = Mock()
        device.screencap.return_value = np.array([[[3, 7, 11]]], dtype=np.uint8)
        output = io.BytesIO()
        serve(device, FragmentedInput(packet({"op": "screencap"})), output)
        response = io.BytesIO(output.getvalue())
        size = struct.unpack("!I", read_exact(response, 4))[0]
        header = json.loads(read_exact(response, size))
        self.assertTrue(header["ok"])
        image = Image.open(io.BytesIO(read_exact(response, header["payload_size"])))
        self.assertEqual(image.getpixel((0, 0)), (11, 7, 3))
        device.close.assert_called_once()
        device.begin_session.assert_not_called()

    def test_connect_does_not_start_input_until_first_action(self) -> None:
        device = Mock()
        device.connected.return_value = False
        device.connect.return_value = True
        self.assertEqual(dispatch(device, {"op": "connect"}), (True, b""))
        device.connect.assert_called_once_with(start_session=False)

    def test_rpc_does_not_allow_arbitrary_device_methods(self) -> None:
        device = Mock()
        with self.assertRaisesRegex(ValueError, "unsupported"):
            dispatch(device, {"op": "__dict__"})
        with self.assertRaisesRegex(ValueError, "invalid"):
            dispatch(device, {"op": "key_down", "args": [True]})
        device.key_down.assert_not_called()

    def test_stop_app_only_targets_endfield(self) -> None:
        device = Mock()
        device.stop_app.return_value = True
        self.assertEqual(dispatch(device, {"op": "stop_app"}), (True, b""))
        device.stop_app.assert_called_once_with("com.hypergryph.endfield")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            dispatch(device, {"op": "stop_app", "args": ["other.app"]})

    def test_invalid_frame_releases_device(self) -> None:
        device = Mock()
        with self.assertRaises(ValueError):
            serve(device, io.BytesIO(struct.pack("!I", MAX_HEADER + 1)), io.BytesIO())
        device.close.assert_called_once()

    def test_failed_input_closes_device_and_returns_framed_error(self) -> None:
        device = Mock()
        device.key_down.side_effect = OSError("connection closed")
        output = io.BytesIO()
        serve(device, io.BytesIO(packet({"op": "key_down", "args": [87]})), output)
        response = io.BytesIO(output.getvalue())
        size = struct.unpack("!I", read_exact(response, 4))[0]
        self.assertFalse(json.loads(read_exact(response, size))["ok"])
        device.close.assert_called()


if __name__ == "__main__":
    unittest.main()
