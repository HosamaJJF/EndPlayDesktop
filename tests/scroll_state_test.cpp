#include "ScrollState.h"

#include <cstdlib>
#include <iostream>

using namespace endplaydesktop;

static void Require(bool result, const char* message)
{
    if (!result) { std::cerr << message << '\n'; std::exit(1); }
}

static void CheckTrackpadGestures()
{
    HostScrollState host;
    HostScrollEvent event { .dx = 2.5f, .dy = -7.5f, .precise = true, .phase = 1 };
    auto result = host.update(event);
    Require(result.dx == -0.25f && result.dy == -0.75f && !result.consume,
            "map and list trackpad input must retain continuous deltas and original event delivery");
    event.phase = 0;
    event.momentum = 4;
    result = host.update(event);
    Require(result.dy == -0.75f && !result.consume, "menu scrolling must retain trackpad inertia");

    event = { .dy = 2, .precise = true, .world = true, .phase = 1, .time = 1 };
    result = host.update(event);
    Require(result.dy == 0 && result.consume,
            "world selection must accumulate sub-detent motion and consume unfiltered host input");
    event.dy = 3;
    event.phase = 4;
    event.time = 1.016;
    Require(host.update(event).dy == 0, "small deltas across frames must not each select an option");
    event.dy = 34;
    event.time = 1.032;
    Require(host.update(event).dy == 0, "39 points must not trigger a world detent");
    event.dy = 2;
    event.time = 1.048;
    Require(host.update(event).dy == 1, "crossing 40 points must emit a world detent");
    event.dy = 119;
    event.time = 2;
    Require(host.update(event).dy == 3,
            "continued sliding must emit all whole detents and preserve fractional distance across a pause");
    event.dy = 160;
    Require(host.update(event).dy == 4, "a long swipe must keep switching without lifting fingers");
    event.dy = 80;
    event.phase = 8;
    Require(host.update(event).dy == 2, "a final movement delivered with finger lift must not be lost");
    event.phase = 0;
    event.momentum = 1;
    event.dy = 200;
    result = host.update(event);
    Require(result.dy == 0 && result.consume, "world selection must discard inertia after finger lift");

    event = { .dy = -99, .precise = true, .world = true, .phase = 1, .time = 3 };
    Require(host.update(event).dy == -2, "negative swipes must emit every whole detent too");
    event.phase = 4;
    event.dy = 99;
    Require(host.update(event).dy == 2, "reversing within a gesture must work without lifting fingers");
    event.phase = 16;
    Require(host.update(event).dy == 0, "cancelling a gesture must not select anything");

    event = { .dy = 20, .precise = true, .world = true, .phase = 1, .time = 4 };
    Require(host.update(event).dy == 0, "a short gesture must stay below the selection threshold");
    event.dy = 0;
    event.phase = 8;
    host.update(event);
    event.dy = 20;
    event.phase = 1;
    Require(host.update(event).dy == 0, "finger lift must discard a previous gesture's partial movement");
    host.reset();
    event.phase = 4;
    Require(host.update(event).dy == 0, "focus reset must discard partial movement too");

    event = { .dy = 20, .precise = true, .world = true, .time = 5 };
    Require(host.update(event).dy == 0, "phaseless precise input must use the same distance threshold");
    event.time = 5.05;
    Require(host.update(event).dy == 1, "phaseless events must accumulate distance within a burst");
    event.dy = 80;
    event.time = 5.1;
    Require(host.update(event).dy == 2, "phaseless devices must also allow several steps in a single burst");
    event.dy = 20;
    event.time = 5.15;
    Require(host.update(event).dy == 0, "fractional phaseless distance must wait for a full detent");
    event.time = 5.4;
    Require(host.update(event).dy == 0, "idle must discard only unfinished phaseless distance");
    event.time = 5.45;
    Require(host.update(event).dy == 1, "input after idle must keep accumulating normally");
    event.dy = 20;
    Require(host.update(event).dy == 0, "retain partial world distance before opening a menu");
    event.world = false;
    event.dy = 5;
    result = host.update(event);
    Require(result.dy == 0.5f && !result.consume, "opening a menu must immediately restore continuous scrolling");
    event.world = true;
    event.dy = 20;
    Require(host.update(event).dy == 0, "returning from a menu must not reuse the previous world's partial distance");
    event = { .dy = 0.1f, .world = true };
    Require(host.update(event).dy == 1 && host.update(event).dy == 1,
            "ordinary wheel detents must remain independent of the trackpad gesture policy");
}

static void CheckTrackpadDistanceConservation()
{
    // The OS can merge or split the same swipe into very different callback
    // counts. Neither that batching nor swipe direction should set its speed.
    for (int direction : { -1, 1 }) {
        for (int parts : { 1, 7, 293 }) {
            HostScrollState host;
            float emitted = 0;
            int remaining = direction * 293;
            for (int i = 0; i < parts; ++i) {
                const int delta = remaining / (parts - i);
                remaining -= delta;
                emitted += host.update({ .dy = static_cast<float>(delta), .precise = true, .world = true,
                                         .phase = i == 0 ? 1u : 4u }).dy;
            }
            Require(emitted == direction * 7,
                    "the same 293-point swipe must produce seven detents regardless of event batching or direction");
            Require(host.update({ .dy = direction * 27.0f, .precise = true, .world = true, .phase = 4 }).dy == direction,
                    "distance remaining after whole detents must contribute to the next detent");
        }
    }
}

int main()
{
    CheckTrackpadGestures();
    CheckTrackpadDistanceConservation();
    Require(MacScrollTicks(0, 0.1f, false) == std::pair(0.0f, 1.0f),
            "a fractional Cocoa wheel event must still produce a full detent");
    Require(MacScrollTicks(-0.1f, -0.3f, false) == std::pair(1.0f, -1.0f),
            "wheel direction must map to Windows axes in both directions");
    Require(MacScrollTicks(2, -3, false) == std::pair(-2.0f, -3.0f),
            "coalesced wheel ticks must not collapse to a single tick");
    Require(MacScrollTicks(2.5f, -7.5f, true) == std::pair(-0.25f, -0.75f),
            "precise trackpad movement must preserve fractional ticks");
    Require(MacScrollTicks(0, 0, false) == std::pair(0.0f, 0.0f),
            "a gesture phase with no movement must not scroll");

    ScrollState scroll;
    scroll.add(0, 120, 100, true);
    Require(scroll.read(100) == std::pair(0.0f, 1.0f),
            "one physical wheel tick must be one Legacy tick rather than 120");
    Require(scroll.axis(100) == 0.1f && scroll.read(100) == std::pair(0.0f, 1.0f),
            "mouseScrollDelta and ScrollWheel axis readers in one frame must agree");
    Require(scroll.read(101) == std::pair(0.0f, 0.0f),
            "the next frame must not replay a wheel tick, regardless of elapsed milliseconds");

    scroll.add(60, 240, 101, false);
    scroll.add(180, -120, 101, false);
    Require(scroll.read(102) == std::pair(2.0f, 1.0f),
            "late horizontal and vertical wheel events must accumulate instead of overwriting");
    Require(scroll.read(103) == std::pair(0.0f, 0.0f),
            "accumulated wheel input must be consumed exactly once");

    scroll.add(0, 30, 104, true);
    Require(scroll.read(104) == std::pair(0.0f, 0.25f),
            "high-resolution scrolling must retain fractional Legacy movement");
    scroll.add(0, 30, 104, true);
    Require(scroll.read(104) == std::pair(0.0f, 0.25f),
            "a late event must not change values already observed in the current frame");
    Require(scroll.read(105) == std::pair(0.0f, 0.25f),
            "a late event must be delivered once on the following frame");

    scroll.add(0, 120, 106, true);
    scroll.add(0, 240, 106, false);
    Require(scroll.read(106) == std::pair(0.0f, 3.0f),
            "player and automation wheel input must both contribute");
    scroll.reset(false);
    Require(scroll.read(106) == std::pair(0.0f, 1.0f),
            "ending automation must preserve the player's sampled wheel input");
    scroll.reset(true);
    Require(scroll.read(106) == std::pair(0.0f, 0.0f),
            "focus loss must clear the player's sampled wheel input");

    scroll.add(0, -120, 107, false);
    scroll.add(0, 240, 107, true);
    scroll.reset(true);
    Require(scroll.read(107) == std::pair(0.0f, -1.0f),
            "focus loss must preserve pending automation wheel input");
    scroll.add(0, 480, 108, true);
    Require(scroll.read(111) == std::pair(0.0f, 0.0f),
            "unread scroll input must expire instead of firing on a later screen");

    std::cout << "scroll unit conversion and single-frame checks passed\n";
}
