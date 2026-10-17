#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

namespace endplaydesktop
{

constexpr uint32_t FourCC(char a, char b, char c, char d)
{
    return (uint32_t(a) << 24) | (uint32_t(b) << 16) | (uint32_t(c) << 8) | uint32_t(d);
}

#pragma pack(push, 1)
struct InputEventHeader
{
    uint32_t type = FourCC('S', 'T', 'A', 'T');
    uint16_t size = 0;
    uint16_t device = 0;
    double time = 0;
    uint32_t event_id = 0;
};

struct MouseState
{
    float x = 0, y = 0;
    float dx = 0, dy = 0;
    float scroll_x = 0, scroll_y = 0;
    uint16_t buttons = 0;
    uint16_t display = 0;
    uint16_t click_count = 0;
};
#pragma pack(pop)

static_assert(sizeof(InputEventHeader) == 20);
static_assert(sizeof(MouseState) == 30);
static_assert(offsetof(MouseState, buttons) == 24);

// MaaEnd Desktop uses resolution-dependent Windows displacement. Endfield's
// current PC input path was measured at about 0.25 degrees per Unity axis unit.
// Only automated deltas use this conversion; physical mouse input is unchanged.
void NormalizeDesktopDelta(MouseState& state, int width, int height);

// VK 是 MaaEnd 的输入边界；Unity Key 是位图索引，Legacy KeyCode 是另一套编号。
std::optional<int> Win32ToUnityKey(int vk);
std::optional<int> Win32ToLegacyKey(int vk);
std::optional<int> HidToWin32Key(int hid);
std::vector<uint8_t> MakeStateEvent(uint16_t device, uint32_t format, double time,
                                  const void* state, size_t size);

} // namespace endplaydesktop
