#pragma once

#include <cstdint>
#include <utility>

namespace endplaydesktop
{

// Legacy GetAxis may be read repeatedly in a frame. All reads see the same
// accumulated displacement, but subsequent frames must not replay it.
class FrameDelta
{
public:
    void add(float dx, float dy, uint32_t frame)
    {
        if (pending_ && frame - pending_frame_ > 1) pending_x_ = pending_y_ = 0;
        pending_x_ += dx;
        pending_y_ += dy;
        pending_frame_ = frame;
        pending_ = true;
    }

    std::pair<float, float> read(uint32_t frame)
    {
        if (sampled_ && frame == sampled_frame_) return { x_, y_ };
        x_ = y_ = 0;
        if (pending_ && frame - pending_frame_ <= 1) {
            x_ = pending_x_;
            y_ = pending_y_;
        }
        pending_x_ = pending_y_ = 0;
        pending_ = false;
        sampled_ = true;
        sampled_frame_ = frame;
        return { x_, y_ };
    }

    void reset() { *this = {}; }

private:
    float pending_x_ = 0, pending_y_ = 0, x_ = 0, y_ = 0;
    uint32_t pending_frame_ = 0, sampled_frame_ = 0;
    bool pending_ = false, sampled_ = false;
};

} // namespace endplaydesktop
