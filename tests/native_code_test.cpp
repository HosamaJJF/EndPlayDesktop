#include "NativeCode.h"

#include <array>
#include <cstdlib>
#include <cstring>
#include <iostream>

using namespace endplaydesktop;

static void Require(bool value, const char* message)
{
    if (!value) { std::cerr << message << '\n'; std::exit(1); }
}

static uint32_t Adrp(uintptr_t pc, uintptr_t target, unsigned reg)
{
    const uint64_t value = static_cast<int64_t>((target & ~uintptr_t(4095)) - (pc & ~uintptr_t(4095))) / 4096;
    return 0x90000000 | ((value & 3) << 29) | (((value >> 2) & 0x7ffff) << 5) | reg;
}

int main()
{
    alignas(4096) std::array<uint32_t, 1024> text {};
    alignas(4096) std::array<uint8_t, 4096> data {};
    auto pc = [&](size_t index) { return reinterpret_cast<uintptr_t>(text.data() + index); };
    const uintptr_t slot = reinterpret_cast<uintptr_t>(data.data());
    const uintptr_t name = slot + 64;
    const char* icall = "UnityEngine.Input::get_mousePresent()";
    std::memcpy(reinterpret_cast<void*>(name), icall, std::strlen(icall) + 1);
    text[0] = Adrp(pc(0), slot, 8);
    text[1] = 0xf9400108 | (((slot & 4095) / 8) << 10);
    text[2] = 0xb5000008; // CBNZ X8, cached target
    text[3] = Adrp(pc(3), name, 0);
    text[4] = 0x91000000 | ((name & 4095) << 10);
    text[5] = 0xd65f03c0;
    NativeCode code({ { pc(0), pc(text.size()), false, true }, { slot, slot + data.size(), true, false } });
    Require(code.icallSlot(text.data(), icall) == reinterpret_cast<void**>(slot), "generated icall cache must resolve");
    Require(code.icallSlot(text.data(), "UnityEngine.Input::GetAxis(System.String)") == nullptr, "wrong icall name must not match");
    NativeCode read_only({ { pc(0), pc(text.size()), false, true }, { slot, slot + data.size(), false, false } });
    Require(read_only.icallSlot(text.data(), icall) == nullptr, "read-only cache must not be patched");
    text[16] = 0x14000000 | ((0 - 16) & 0x03ffffff);
    Require(code.icallSlot(text.data() + 16, icall) == reinterpret_cast<void**>(slot), "leading branch must resolve");
    text[20] = 0x52800021;
    text[21] = 0x94000000 | (104 - 21);
    text[22] = 0xd65f03c0;
    text[100] = 0xa9bf4ff4;
    text[104] = 0xaa0003e0;
    Require(code.keyStateFunction(text.data() + 20) == text.data() + 100, "hidden key state entry must resolve from handleCommand");
    Require(code.keyStateFunction(reinterpret_cast<void*>(slot)) == nullptr, "data memory must not be parsed as code");
    std::cout << "native code checks passed\n";
}
