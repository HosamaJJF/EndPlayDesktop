#include "InputState.h"

#include <cstring>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace endplaydesktop
{

void NormalizeDesktopDelta(MouseState& state, int width, int height)
{
    if (width <= 0 || height <= 0) throw std::invalid_argument("invalid desktop render size");
    // Keep the Windows boundary aligned with MaaEnd MapNavigator/navi_config.h.
    constexpr double turn_units_per_width = 2.23006;
    constexpr double game_degrees_per_axis_unit = 0.25;
    const double yaw_units_per_degree = std::lround(turn_units_per_width * width) / 360.0;
    const double pitch_units_per_degree = turn_units_per_width * height / 180.0;
    state.dx /= static_cast<float>(yaw_units_per_degree * game_degrees_per_axis_unit);
    state.dy /= static_cast<float>(pitch_units_per_degree * game_degrees_per_axis_unit);
}

std::optional<int> Win32ToUnityKey(int vk)
{
    if (vk >= 'A' && vk <= 'Z') return 15 + vk - 'A';
    if (vk >= '1' && vk <= '9') return 41 + vk - '1';
    if (vk >= 0x60 && vk <= 0x69) return 84 + vk - 0x60;
    if (vk >= 0x70 && vk <= 0x7b) return 94 + vk - 0x70;
    switch (vk) {
    case '0': return 50;
    case 0x08: return 65;
    case 0x09: return 3;
    case 0x0d: return 2;
    case 0x10: case 0xa0: return 51;
    case 0xa1: return 52;
    case 0x11: case 0xa2: return 55;
    case 0xa3: return 56;
    case 0x12: case 0xa4: return 53;
    case 0xa5: return 54;
    case 0x13: return 76;
    case 0x14: return 72;
    case 0x1b: return 60;
    case 0x20: return 1;
    case 0x21: return 67;
    case 0x22: return 66;
    case 0x23: return 69;
    case 0x24: return 68;
    case 0x25: return 61;
    case 0x26: return 63;
    case 0x27: return 62;
    case 0x28: return 64;
    case 0x2c: return 74;
    case 0x2d: return 70;
    case 0x2e: return 71;
    case 0x5b: return 57;
    case 0x5c: return 58;
    case 0x5d: return 59;
    case 0x6a: return 79;
    case 0x6b: return 80;
    case 0x6d: return 81;
    case 0x6e: return 82;
    case 0x6f: return 78;
    case 0x90: return 73;
    case 0x91: return 75;
    case 0xba: return 6;
    case 0xbb: return 14;
    case 0xbc: return 7;
    case 0xbd: return 13;
    case 0xbe: return 8;
    case 0xbf: return 9;
    case 0xc0: return 4;
    case 0xdb: return 11;
    case 0xdc: return 10;
    case 0xdd: return 12;
    case 0xde: return 5;
    default: return std::nullopt;
    }
}

std::optional<int> Win32ToLegacyKey(int vk)
{
    if (vk >= 'A' && vk <= 'Z') return vk + ('a' - 'A');
    if (vk >= '0' && vk <= '9') return vk;
    if (vk >= 0x70 && vk <= 0x7b) return 282 + vk - 0x70;
    switch (vk) {
    case 0x08: return 8;
    case 0x09: return 9;
    case 0x0d: return 13;
    case 0x10: case 0xa0: return 304;
    case 0xa1: return 303;
    case 0x11: case 0xa2: return 306;
    case 0xa3: return 305;
    case 0x12: case 0xa4: return 308;
    case 0xa5: return 307;
    case 0x1b: return 27;
    case 0x20: return 32;
    case 0x25: return 276;
    case 0x26: return 273;
    case 0x27: return 275;
    case 0x28: return 274;
    default: return std::nullopt;
    }
}

std::optional<int> HidToWin32Key(int hid)
{
    if (hid >= 4 && hid <= 29) return 'A' + hid - 4;
    if (hid >= 30 && hid <= 38) return '1' + hid - 30;
    if (hid >= 58 && hid <= 69) return 0x70 + hid - 58;
    switch (hid) {
    case 39: return '0';
    case 40: return 0x0d;
    case 41: return 0x1b;
    case 42: return 0x08;
    case 43: return 0x09;
    case 44: return 0x20;
    case 45: return 0xbd;
    case 46: return 0xbb;
    case 47: return 0xdb;
    case 48: return 0xdd;
    case 49: return 0xdc;
    case 51: return 0xba;
    case 52: return 0xde;
    case 53: return 0xc0;
    case 54: return 0xbc;
    case 55: return 0xbe;
    case 56: return 0xbf;
    case 57: return 0x14;
    case 73: return 0x2d;
    case 74: return 0x24;
    case 75: return 0x21;
    case 76: return 0x2e;
    case 77: return 0x23;
    case 78: return 0x22;
    case 79: return 0x27;
    case 80: return 0x25;
    case 81: return 0x28;
    case 82: return 0x26;
    case 224: return 0xa2;
    case 225: return 0xa0;
    case 226: return 0xa4;
    case 227: return 0x5b;
    case 228: return 0xa3;
    case 229: return 0xa1;
    case 230: return 0xa5;
    case 231: return 0x5c;
    default: return std::nullopt;
    }
}

std::vector<uint8_t> MakeStateEvent(uint16_t device, uint32_t format, double time,
                                  const void* state, size_t size)
{
    constexpr size_t kPrefix = sizeof(InputEventHeader) + sizeof(uint32_t);
    if (size > std::numeric_limits<uint16_t>::max() - kPrefix) {
        throw std::invalid_argument("input state exceeds event size limit");
    }
    // sizeInBytes 不包含尾部对齐字节，分配区仍按 Input System 的 4 字节要求对齐。
    std::vector<uint8_t> result((kPrefix + size + 3) & ~size_t(3));
    InputEventHeader header;
    header.size = static_cast<uint16_t>(kPrefix + size);
    header.device = device;
    header.time = time;
    std::memcpy(result.data(), &header, sizeof(header));
    std::memcpy(result.data() + sizeof(header), &format, sizeof(format));
    std::memcpy(result.data() + kPrefix, state, size);
    return result;
}

} // namespace endplaydesktop
