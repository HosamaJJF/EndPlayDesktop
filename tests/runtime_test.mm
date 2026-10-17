#include "Runtime.h"
#include "InputState.h"

#include <cstdlib>
#include <iostream>

using namespace endplaydesktop;
extern "C" {
void EPDTestReset();
void EPDTestUseManagerOnly();
int EPDTestPlatform();
int EPDTestFocus();
bool EPDTestBackground();
void EPDTestFailEnable(bool);
bool EPDTestKeyDown(int);
void EPDTestMouse(MouseState*);
}

static MouseState ReadMouse()
{
    MouseState result;
    EPDTestMouse(&result);
    return result;
}

static void Require(bool result, const char* message)
{
    if (!result) { std::cerr << message << '\n'; std::exit(1); }
}

int main()
{
    @autoreleasepool {
        EPDTestReset();
        bool foreground = true;
        Runtime runtime([&] { return foreground; });
        runtime.tick();
        if (!runtime.ready()) std::cerr << [runtime.status().description UTF8String] << '\n';
        Require(runtime.ready(), "managed runtime initialization must succeed");
        NSDictionary* camera = runtime.command(@{ @"op": @"camera" });
        Require([camera[@"available"] boolValue] && [camera[@"pitch_degrees"] floatValue] == 10
                && [camera[@"yaw_degrees"] floatValue] == 42 && [camera[@"field_of_view"] floatValue] == 60,
                "read-only camera diagnostics must wrap Unity Euler pitch and work without automation");
        Require(!runtime.automationActive(), "camera diagnostics must not start an input session");
        Require(EPDTestPlatform() == 2, "game DeviceInfo must switch to WindowsPlayer");
        Require([runtime.command(@{ @"op": @"begin" })[@"ok"] boolValue], "begin must succeed");
        Require(EPDTestFocus() == 2 && EPDTestBackground(), "automation must allow background input");
        runtime.nativeKey('W', true);
        Require(EPDTestKeyDown(37) && runtime.automationActive(), "manual input must work without changing the automation session");
        runtime.nativeKey('W', false);
        Require([runtime.command(@{ @"op": @"key", @"vk": @87, @"down": @YES })[@"ok"] boolValue], "W must queue a keyboard event");
        Require(EPDTestKeyDown(37), "managed keyboard bit must be set");
        runtime.nativeKey('W', true);
        runtime.command(@{ @"op": @"key", @"vk": @87, @"down": @NO });
        Require(EPDTestKeyDown(37), "automation key-up must preserve a key held by the player");
        runtime.command(@{ @"op": @"key", @"vk": @87, @"down": @YES });
        runtime.nativeReset();
        Require(EPDTestKeyDown(37), "manual focus reset must preserve automation-held keys");
        foreground = false;
        runtime.nativeKey('A', true);
        runtime.nativeButton(1, true);
        Require(!EPDTestKeyDown(15) && ReadMouse().buttons == 0, "input to other applications must not enter the game");
        foreground = true;
        runtime.command(@{ @"op": @"move", @"x": @100, @"y": @200, @"delta": @NO });
        Require(ReadMouse().x == 100 && ReadMouse().y == 519, "top-left screenshot coordinates must flip Y");
        runtime.command(@{ @"op": @"relative", @"dx": @40, @"dy": @-20 });
        Require(ReadMouse().dx > 20 && ReadMouse().dx < 21 && ReadMouse().dy > 8 && ReadMouse().dy < 10,
                "automated camera delta must normalize Windows units and flip Y");
        runtime.nativeDelta(40, 20);
        Require(ReadMouse().dx == 40 && ReadMouse().dy == 20, "manual relative input must retain its original sensitivity");
        runtime.nativePosition(250, 150);
        Require(ReadMouse().x == 250 && ReadMouse().y == 569 && runtime.automationActive(), "manual pointer motion must coexist with automation");
        runtime.nativeKey(0xa2, true);
        runtime.command(@{ @"op": @"key", @"vk": @0x11, @"down": @YES });
        runtime.nativeKey(0xa2, false);
        Require(EPDTestKeyDown(55), "generic and physical left Ctrl must share the same effective key state");
        runtime.nativeButton(0, true);
        runtime.command(@{ @"op": @"button", @"button": @0, @"down": @YES });
        runtime.nativeButton(0, false);
        Require(ReadMouse().buttons == 1, "manual mouse-up must preserve an automation-held button");
        runtime.nativeButton(1, true);
        Require(![runtime.command(@{ @"op": @"key", @"vk": @999, @"down": @YES })[@"ok"] boolValue], "invalid key must fail without corrupting state");
        runtime.endSession();
        Require(!EPDTestKeyDown(37), "ending the session must release held keys");
        Require(!EPDTestKeyDown(55) && ReadMouse().buttons == 2, "ending automation must release its inputs and preserve a player-held button");
        runtime.nativeReset();
        Require(ReadMouse().buttons == 0, "manual focus reset must release player-held buttons");
        Require(EPDTestFocus() == 0 && !EPDTestBackground(), "ending the session must restore focus settings");
        runtime.nativeKey('W', true);
        Require(EPDTestKeyDown(37), "manual input must resume after automation");
        runtime.nativeReset();
        Require(!EPDTestKeyDown(37), "manual focus loss must release native held keys");
        EPDTestFailEnable(true);
        Require(![runtime.command(@{ @"op": @"begin" })[@"ok"] boolValue], "partial session failure must be reported");
        Require(!runtime.automationActive() && EPDTestFocus() == 0 && !EPDTestBackground(), "partial session failure must roll back settings");
        EPDTestFailEnable(false);
        EPDTestUseManagerOnly();
        Runtime stripped_runtime;
        stripped_runtime.tick();
        Require(stripped_runtime.ready(), "stripped public wrappers must fall back to InputManager");
        stripped_runtime.command(@{ @"op": @"begin" });
        stripped_runtime.command(@{ @"op": @"key", @"vk": @87, @"down": @YES });
        Require(EPDTestKeyDown(37), "InputManager fallback must queue the same key state");
        stripped_runtime.endSession();
        std::cout << "managed runtime checks passed\n";
    }
}
