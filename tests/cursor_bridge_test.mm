#include "Runtime.h"
#include "InputState.h"

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <limits>

using namespace endplaydesktop;
extern "C" {
void EPDTestReset();
void EPDTestEnableCursorHooks();
void EPDTestSetCursorVisible(bool);
bool EPDTestCursorVisible();
void EPDTestSetCursorLock(int);
int EPDTestCursorLock();
int64_t EPDTestCursorCommand(int, int, void*, int);
void EPDTestLegacyPosition(float*, float*);
void EPDTestAdvanceCursorFrame();
void EPDTestMouse(MouseState*);
bool EPDTestKeyDown(int);
}

static void Require(bool value, const char* message)
{
    if (!value) { std::cerr << message << '\n'; std::exit(1); }
}

static void RequirePosition(float x, float y)
{
    MouseState mouse;
    EPDTestMouse(&mouse);
    float legacy_x, legacy_y;
    EPDTestLegacyPosition(&legacy_x, &legacy_y);
    Require(mouse.x == x && mouse.y == y && legacy_x == x && legacy_y == y,
            "Input System and Legacy must agree on cursor position");
}

static int64_t Warp(float x, float y, int device = 8)
{
    float point[] { x, y };
    return EPDTestCursorCommand(device, FourCC('W', 'A', 'R', 'P'), point, sizeof(point));
}

int main()
{
    @autoreleasepool {
        EPDTestReset();
        EPDTestEnableCursorHooks();
        // Preserve pre-existing game state while installing all icall hooks.
        EPDTestSetCursorVisible(false);
        EPDTestSetCursorLock(2);
        {
            Runtime runtime([] { return false; });
            runtime.tick();
            if (!runtime.ready()) std::cerr << [runtime.status().description UTF8String] << '\n';
            Require(runtime.ready(), "cursor-capable runtime must initialize");
            Require(!EPDTestCursorVisible() && EPDTestCursorLock() == 2 && !runtime.wantsPointerLock(),
                    "visibility, confinement, and locking must remain independent");
            EPDTestSetCursorVisible(true);
            EPDTestSetCursorLock(0);
            Require(Warp(100, 200) == 1, "game warp must work in background without an automation session");
            RequirePosition(100, 200);
            Require(!runtime.automationActive(), "a game cursor request must not begin automation");

            Require(Warp(-20, 740) == 1, "unlocked game warps may leave the game view");
            RequirePosition(-20, 740);
            EPDTestSetCursorLock(2);
            RequirePosition(0, 719);
            Require(Warp(2000, -1) == 1, "confined warps must be accepted and clamped");
            RequirePosition(1279, 0);

            // Reproduce the cross-page stale-pointer sequence without any
            // knowledge of tasks, templates, or the game's panel names.
            EPDTestSetCursorLock(0);
            runtime.command(@{ @"op": @"begin" });
            runtime.command(@{ @"op": @"move", @"x": @843, @"y": @659, @"delta": @NO });
            runtime.command(@{ @"op": @"button", @"button": @0, @"down": @YES });
            RequirePosition(843, 60);
            EPDTestSetCursorVisible(false);
            Require(!runtime.wantsPointerLock() && EPDTestCursorLock() == 0,
                    "hiding an unlocked cursor must not fabricate a lock request");
            RequirePosition(843, 60);
            EPDTestSetCursorLock(1);
            Require(runtime.wantsPointerLock(), "explicit Locked mode must request host locking");
            RequirePosition(640, 360);
            EPDTestSetCursorVisible(true);
            Require(EPDTestCursorVisible() && EPDTestCursorLock() == 1 && runtime.wantsPointerLock(),
                    "showing the cursor must not unlock it");
            Require(Warp(123, 234) == 1, "a locked warp is temporary until the next frame");
            RequirePosition(123, 234);
            runtime.tick();
            RequirePosition(123, 234);
            EPDTestAdvanceCursorFrame();
            runtime.tick();
            RequirePosition(640, 360);
            EPDTestSetCursorLock(0);
            runtime.command(@{ @"op": @"button", @"button": @0, @"down": @NO });
            RequirePosition(640, 360);
            Require(!runtime.wantsPointerLock(), "unlock must release the host-lock request");

            runtime.command(@{ @"op": @"button", @"button": @0, @"down": @YES });
            runtime.command(@{ @"op": @"key", @"vk": @87, @"down": @YES });
            Require(Warp(900, 400) == 1, "a game warp while pressed must update the authoritative mouse state");
            MouseState mouse;
            EPDTestMouse(&mouse);
            Require(mouse.buttons == 1 && EPDTestKeyDown(37), "game warps must preserve held mouse buttons and keys");
            runtime.command(@{ @"op": @"button", @"button": @0, @"down": @NO });
            RequirePosition(900, 400);
            EPDTestMouse(&mouse);
            Require(mouse.buttons == 0 && mouse.dx == 0 && mouse.dy == 0,
                    "warp must preserve button transitions without camera movement");

            Require(Warp(10, 20, 7) == -99, "another device's commands must reach the original backend");
            Require(EPDTestCursorCommand(8, FourCC('T', 'E', 'S', 'T'), nullptr, 0) == -99,
                    "unrelated mouse commands must reach the original backend");
            Require(EPDTestCursorCommand(8, FourCC('W', 'A', 'R', 'P'), nullptr, 8) == -1,
                    "malformed warp payloads must fail without touching mouse state");
            float point[] { 1, 2 };
            Require(EPDTestCursorCommand(8, FourCC('W', 'A', 'R', 'P'), point, 4) == -1,
                    "truncated warp payloads must fail");
            Require(Warp(std::numeric_limits<float>::quiet_NaN(), 0) == -1,
                    "non-finite game coordinates must fail");
            RequirePosition(900, 400);
            runtime.endSession();
            RequirePosition(900, 400);
            Require([runtime.status()[@"game_cursor_warps"] unsignedLongLongValue] == 5,
                    "only successfully handled game warps must be counted");
        }
        Require(Warp(1, 2) == -99, "destroying the runtime must restore the native command backend");
        EPDTestSetCursorLock(2);
        Require(EPDTestCursorLock() == 2, "destroying the runtime must restore original Cursor accessors");
        std::cout << "cursor bridge checks passed\n";
    }
}
