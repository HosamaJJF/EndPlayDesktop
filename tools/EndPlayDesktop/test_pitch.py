from __future__ import annotations

import unittest
from unittest.mock import patch

from .client import BridgeError
from .pitch import PitchFeedback


class CameraBridge:
    def __init__(self, pitch: float, stalled: bool = False) -> None:
        self.pitch = pitch
        self.stalled = stalled
        self.movements: list[float] = []

    def request(self, op: str) -> dict:
        return {"ok": True, "available": True, "pitch_degrees": self.pitch}

    def apply(self, op: str, **fields: float) -> dict:
        dy = fields["dy"]
        self.movements.append(dy)
        if not self.stalled:
            # 相机在中心和上限附近的响应不同，不能靠一个固定倍数通过该测试。
            gain = 0.02 + 0.000006 * (self.pitch + 30) ** 2
            self.pitch = min(86, max(-54, self.pitch - dy * gain))
        return {}


class PitchTests(unittest.TestCase):
    def setUp(self) -> None:
        sleep = patch("tools.EndPlayDesktop.pitch.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_thirty_degrees_converges_with_nonlinear_gain(self) -> None:
        bridge = CameraBridge(86)
        feedback = PitchFeedback()
        feedback.turn(bridge, 1080, 401)
        self.assertAlmostEqual(bridge.pitch, 86 - 401 / 13.38036, delta=0.5)
        self.assertGreater(len(bridge.movements), 1)

    def test_zipline_adjustment_uses_nominal_upper_reference_after_reset(self) -> None:
        bridge = CameraBridge(-13)
        feedback = PitchFeedback()
        feedback.turn(bridge, 1080, -2408)
        self.assertEqual(bridge.pitch, 86)
        feedback.turn(bridge, 1080, 401)
        self.assertAlmostEqual(bridge.pitch, 90 - 401 / 13.38036, delta=0.5)

    def test_lower_limit_and_adjustment_use_nominal_minus_sixty(self) -> None:
        bridge = CameraBridge(10)
        feedback = PitchFeedback()
        feedback.turn(bridge, 1080, 2408)
        self.assertEqual(bridge.pitch, -54)
        feedback.turn(bridge, 1080, -401)
        self.assertAlmostEqual(bridge.pitch, -60 + 401 / 13.38036, delta=0.5)

    def test_stalled_camera_is_rejected_without_blind_repetition(self) -> None:
        bridge = CameraBridge(0, stalled=True)
        with self.assertRaisesRegex(BridgeError, "没有响应"):
            PitchFeedback().turn(bridge, 1080, 401)
        self.assertEqual(len(bridge.movements), 2)

    def test_unresponsive_center_is_not_mistaken_for_a_reset_limit(self) -> None:
        bridge = CameraBridge(0, stalled=True)
        feedback = PitchFeedback()
        with self.assertRaisesRegex(BridgeError, "没有响应"):
            feedback.turn(bridge, 1080, -2408)
        self.assertIsNone(feedback._limit_reference)
        self.assertEqual(len(bridge.movements), 2)


if __name__ == "__main__":
    unittest.main()
