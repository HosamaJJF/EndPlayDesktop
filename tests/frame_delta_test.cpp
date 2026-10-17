#include "FrameDelta.h"

#include <cstdlib>
#include <iostream>

using namespace endplaydesktop;

static void Require(bool result, const char* message)
{
    if (!result) { std::cerr << message << '\n'; std::exit(1); }
}

int main()
{
    FrameDelta delta;
    delta.add(10, -5, 100);
    delta.add(20, 2, 100);
    Require(delta.read(100) == std::pair(30.0f, -3.0f), "events before the first read must accumulate");
    Require(delta.read(100) == std::pair(30.0f, -3.0f), "multiple axis readers in one frame must agree");
    Require(delta.read(101) == std::pair(0.0f, 0.0f), "the next frame must not replay displacement");
    delta.add(4, 7, 101);
    Require(delta.read(101) == std::pair(0.0f, 0.0f), "events after a frame's reads must wait for the next frame");
    Require(delta.read(102) == std::pair(4.0f, 7.0f), "late events must be delivered to the next frame");
    delta.add(300, 200, 102);
    Require(delta.read(105) == std::pair(0.0f, 0.0f), "unread menu events must expire rather than move the camera later");
    delta.add(100, 100, 106);
    delta.add(3, 2, 109);
    Require(delta.read(109) == std::pair(3.0f, 2.0f), "new input must discard stale pending input");
    delta.reset();
    Require(delta.read(109) == std::pair(0.0f, 0.0f), "session release must clear the current frame too");
    delta.add(5, 6, UINT32_MAX);
    Require(delta.read(0) == std::pair(5.0f, 6.0f), "frame counter rollover must preserve next-frame events");
    std::cout << "single-frame delta checks passed\n";
}
