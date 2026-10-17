from __future__ import annotations

import math
import time

from .client import BridgeClient, BridgeError


class PitchFeedback:
    """将桌面俯仰位移转换为真实相机角度，用反馈处理滑索瞄准的非线性响应。"""

    def __init__(self) -> None:
        self._limit_reference: tuple[float, float] | None = None

    @staticmethod
    def _read(bridge: BridgeClient) -> float:
        result = bridge.request("camera")
        pitch = result.get("pitch_degrees")
        if not result.get("available") or type(pitch) not in (int, float) or not math.isfinite(pitch):
            raise BridgeError("无法读取真实相机俯仰；需要 EndPlayDesktop 0.1.7 或更新版本与世界相机")
        return float(pitch)

    def _settled(self, bridge: BridgeClient, deadline: float) -> float:
        previous = self._read(bridge)
        stable = 0
        sample_deadline = min(deadline, time.monotonic() + 0.25)
        while time.monotonic() < sample_deadline:
            time.sleep(0.01)
            current = self._read(bridge)
            stable = stable + 1 if abs(current - previous) < 0.03 else 0
            if stable >= 3:
                return current
            previous = current
        return previous

    def turn(self, bridge: BridgeClient, height: int, dy: int) -> None:
        if height <= 0:
            raise BridgeError("未连接游戏渲染尺寸，不能换算俯仰角")
        units_per_degree = 2.23006 * height / 180
        degrees = -dy / units_per_degree
        current = self._read(bridge)
        initial = current
        if self._limit_reference and abs(current - self._limit_reference[0]) <= 1:
            # 滑索 Pipeline 把复位上限记为 +90°、下限记为 -60°。
            # 渲染相机因偏移并不恰好处在该角度，首次调整须使用同一基准。
            initial = self._limit_reference[1]
        self._limit_reference = None
        seek_limit = abs(degrees) >= 150
        target = (90 if degrees > 0 else -60) if seek_limit else initial + degrees
        deadline = time.monotonic() + 5
        pixels_per_degree = units_per_degree * 3.5
        unchanged = 0
        first = True
        while time.monotonic() < deadline:
            error = target - current
            if abs(error) <= 0.5:
                return
            if first and seek_limit:
                delta = dy
            else:
                # 限位附近增益更高，不能按中心位置的灵敏度一次发完整角度。
                magnitude = min(268, abs(error) * 10, abs(error) * pixels_per_degree * 0.6)
                delta = -math.copysign(max(1, magnitude), error)
            bridge.apply("relative", dx=0, dy=delta)
            first = False
            after = self._settled(bridge, deadline)
            change = after - current
            unchanged = unchanged + 1 if abs(change) < 0.05 else 0
            if unchanged >= 2:
                if (error > 0 and after >= 80) or (error < 0 and after <= -45):
                    self._limit_reference = (after, 90 if error > 0 else -60)
                    return
                raise BridgeError("相机没有响应俯仰输入，已停止操作")
            if change * error > 0 and abs(change) >= 0.05:
                pixels_per_degree = max(1, min(500, abs(delta / change)))
            current = after
        raise BridgeError("俯仰反馈未在输入时限内收敛，已停止操作")
