#include "InputState.h"

#include <cstdlib>
#include <cstring>
#include <cmath>
#include <iostream>

using namespace endplaydesktop;

static void Require(bool value, const char* message)
{
    if (!value) {
        std::cerr << message << '\n';
        std::exit(1);
    }
}

int main()
{
    Require(FourCC('S', 'T', 'A', 'T') == 0x53544154, "Unity FourCC stores the first character in the high byte");
    Require(FourCC('M', 'O', 'U', 'S') == 0x4d4f5553, "mouse format must match Unity's numeric MOUS constant");
    Require(Win32ToUnityKey('W') == 37, "W must map to Unity Key.W, not macOS keycode");
    Require(Win32ToUnityKey(0x11) == 55, "generic Ctrl must map to left Ctrl");
    Require(Win32ToUnityKey(0xa3) == 56, "right Ctrl must remain distinct");
    Require(Win32ToLegacyKey('W') == 'w', "legacy keyboard uses lowercase ASCII");
    Require(HidToWin32Key(26) == 'W', "GC HID usage must translate to VK");
    Require(!Win32ToUnityKey(0xff), "unknown keys must fail explicitly");
    MouseState turn;
    turn.x = 50; turn.y = 100; turn.buttons = 1;
    turn.dx = 4282; turn.dy = 2408.4648f;
    NormalizeDesktopDelta(turn, 1920, 1080);
    Require(std::abs(turn.dx - 1440) < 0.01f && std::abs(turn.dy - 720) < 0.01f,
            "a Windows full yaw turn and pitch range must map to 360/180 game degrees");
    Require(turn.x == 50 && turn.y == 100 && turn.buttons == 1,
            "delta normalization must preserve UI coordinates and held buttons");
    turn.dx = -2854; turn.dy = 0;
    NormalizeDesktopDelta(turn, 1280, 720);
    Require(std::abs(turn.dx + 1440) < 0.01f && turn.dy == 0,
            "the same turn at 720p must have the same game displacement and preserve sign");
    MouseState mouse;
    mouse.x = 1280;
    mouse.y = 720;
    mouse.buttons = 2;
    const auto event = MakeStateEvent(7, FourCC('M', 'O', 'U', 'S'), 12.5, &mouse, sizeof(mouse));
    InputEventHeader header;
    std::memcpy(&header, event.data(), sizeof(header));
    Require(header.type == FourCC('S', 'T', 'A', 'T'), "event type must be STAT");
    Require(header.size == 54 && event.size() == 56, "event size and allocation alignment differ");
    Require(header.device == 7 && header.time == 12.5, "header fields must survive serialization");
    uint16_t buttons;
    std::memcpy(&buttons, event.data() + 24 + 24, sizeof(buttons));
    Require(buttons == 2, "mouse button offset must match managed MouseState");
    std::cout << "input state checks passed\n";
}
