#pragma once

#include "FrameDelta.h"

#include <cmath>

namespace endplaydesktop
{

inline constexpr float kScrollUnitsPerTick = 120.0f;
inline constexpr float kLegacyScrollAxisPerTick = 0.1f;
inline constexpr float kWorldTrackpadPointsPerTick = 40.0f;

// Cocoa precise deltas are points; ordinary wheel deltas can be fractional
// even for a single detent. Keep trackpads continuous and round wheel events
// away from zero. Cocoa's horizontal axis is opposite to Windows wheel input.
inline std::pair<float, float> MacScrollTicks(float dx, float dy, bool precise)
{
    if (precise) return { -dx / 10.0f, dy / 10.0f };
    const auto ticks = [](float value) { return std::copysign(std::ceil(std::abs(value)), value); };
    return { -ticks(dx), ticks(dy) };
}

struct HostScrollEvent
{
    float dx = 0, dy = 0;
    bool precise = false, world = false;
    uint64_t phase = 0, momentum = 0;
    double time = 0;
};

struct HostScrollResult
{
    float dx, dy;
    bool consume;
};

class HostScrollState
{
public:
    HostScrollResult update(const HostScrollEvent& event)
    {
        const auto [dx, dy] = MacScrollTicks(event.dx, event.dy, event.precise);
        if (!event.precise || !event.world) {
            reset();
            return { dx, dy, false };
        }

        // World candidates need distance-based detents rather than a switch
        // for every small trackpad delta. Retain the fractional distance and
        // emit every whole tick, including multiple ticks in the same gesture.
        // Consume the host event so UIKit cannot also deliver unfiltered input.
        if (event.momentum) {
            reset();
            return { dx, 0, true };
        }
        constexpr uint64_t began = 1, ended = 8, cancelled = 16; // NSEventPhase
        if (event.phase & cancelled) {
            reset();
            return { dx, 0, true };
        }
        const bool new_burst = !event.phase && (event.time - last_time_ >= 0.2 || event.time < last_time_);
        if (!active_ || (event.phase & began) || new_burst) reset();
        active_ = true;
        last_time_ = event.time;

        pending_ += event.dy;
        const float steps = std::trunc(pending_ / kWorldTrackpadPointsPerTick);
        pending_ -= steps * kWorldTrackpadPointsPerTick;
        if (event.phase & ended) reset();
        return { dx, steps, true };
    }

    void reset() { pending_ = 0; last_time_ = 0; active_ = false; }

private:
    float pending_ = 0;
    double last_time_ = 0;
    bool active_ = false;
};

// Input System uses Windows wheel units, while Legacy mouseScrollDelta uses
// ticks. Each source accumulates independently and is sampled once per frame.
class ScrollState
{
public:
    void add(float dx, float dy, uint32_t frame, bool physical)
    {
        (physical ? physical_ : automated_).add(dx / kScrollUnitsPerTick, dy / kScrollUnitsPerTick, frame);
    }

    std::pair<float, float> read(uint32_t frame)
    {
        const auto [px, py] = physical_.read(frame);
        const auto [ax, ay] = automated_.read(frame);
        return { px + ax, py + ay };
    }

    float axis(uint32_t frame) { return read(frame).second * kLegacyScrollAxisPerTick; }

    void reset(bool physical) { (physical ? physical_ : automated_).reset(); }

private:
    FrameDelta physical_, automated_;
};

} // namespace endplaydesktop
