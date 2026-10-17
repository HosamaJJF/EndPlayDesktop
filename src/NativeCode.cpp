#include "NativeCode.h"

#include <cstring>
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#include <utility>

namespace endplaydesktop
{
namespace
{
int64_t SignExtend(uint64_t value, unsigned bits)
{
    const uint64_t sign = uint64_t(1) << (bits - 1);
    return static_cast<int64_t>((value ^ sign) - sign);
}
uint32_t Instruction(uintptr_t address)
{
    uint32_t result;
    std::memcpy(&result, reinterpret_cast<void*>(address), sizeof(result));
    return result;
}
uintptr_t Page(uintptr_t pc, uint32_t instruction)
{
    const uint64_t immediate = ((instruction >> 5) & 0x7ffff) << 2 | ((instruction >> 29) & 3);
    return (pc & ~uintptr_t(4095)) + SignExtend(immediate, 21) * 4096;
}
} // namespace

NativeCode::NativeCode(std::vector<NativeRange> ranges) : ranges_(std::move(ranges)) {}
NativeCode::NativeCode(const void* address)
{
    for (uint32_t index = 0; index < _dyld_image_count(); ++index) {
        const auto* header = reinterpret_cast<const mach_header_64*>(_dyld_get_image_header(index));
        if (header->magic != MH_MAGIC_64) continue;
        const intptr_t slide = _dyld_get_image_vmaddr_slide(index);
        std::vector<NativeRange> ranges;
        const auto* command = reinterpret_cast<const load_command*>(header + 1);
        for (uint32_t i = 0; i < header->ncmds; ++i) {
            if (command->cmd == LC_SEGMENT_64) {
                const auto* segment = reinterpret_cast<const segment_command_64*>(command);
                if (segment->initprot & VM_PROT_READ) {
                    const uintptr_t start = segment->vmaddr + slide;
                    ranges.push_back({ start, start + segment->vmsize,
                                       (segment->initprot & VM_PROT_WRITE) != 0, (segment->initprot & VM_PROT_EXECUTE) != 0 });
                }
            }
            command = reinterpret_cast<const load_command*>(reinterpret_cast<const uint8_t*>(command) + command->cmdsize);
        }
        for (const auto& range : ranges) {
            if (range.begin <= reinterpret_cast<uintptr_t>(address) && reinterpret_cast<uintptr_t>(address) < range.end) {
                ranges_ = std::move(ranges);
                return;
            }
        }
    }
}
bool NativeCode::contains(uintptr_t address, size_t size, bool executable) const
{
    for (const auto& range : ranges_) {
        if ((!executable || range.executable) && address >= range.begin && address < range.end && size <= range.end - address) return true;
    }
    return false;
}
uintptr_t NativeCode::followBranch(uintptr_t address) const
{
    for (unsigned i = 0; i < 8; ++i) {
        if (!contains(address, 4, true)) return 0;
        const uint32_t word = Instruction(address);
        if ((word & 0xfc000000) != 0x14000000) return address;
        address += SignExtend(word & 0x03ffffff, 26) * 4;
    }
    return 0;
}
void** NativeCode::icallSlot(const void* method, const char* name) const
{
    const uintptr_t start = followBranch(reinterpret_cast<uintptr_t>(method));
    if (!start) return nullptr;
    for (unsigned i = 0; i < 128; ++i) {
        const uintptr_t pc = start + i * 4;
        if (!contains(pc, 8, true)) break;
        const uint32_t a = Instruction(pc), b = Instruction(pc + 4);
        if (a == 0xd65f03c0) break;
        // Require the exact generated icall name; do not hook an arbitrary global load.
        if (i >= 3 && (a & 0x9f00001f) == 0x90000000 && (b & 0xff8003ff) == 0x91000000) {
            const uintptr_t string = Page(pc, a) + (((b >> 10) & 4095) << ((b & 0x00400000) ? 12 : 0));
            if (contains(string, std::strlen(name) + 1) && std::strcmp(reinterpret_cast<const char*>(string), name) == 0) {
                const uint32_t load_page = Instruction(pc - 12), load = Instruction(pc - 8);
                if ((load_page & 0x9f000000) != 0x90000000 || (load & 0xffc00000) != 0xf9400000
                    || ((load >> 5) & 31) != (load_page & 31)) continue;
                const uintptr_t slot = Page(pc - 12, load_page) + ((load >> 10) & 4095) * 8;
                for (const auto& range : ranges_) {
                    if (range.writable && slot >= range.begin && slot + sizeof(void*) <= range.end) return reinterpret_cast<void**>(slot);
                }
            }
        }
    }
    return nullptr;
}
void* NativeCode::keyStateFunction(const void* handle_command) const
{
    const uintptr_t start = followBranch(reinterpret_cast<uintptr_t>(handle_command));
    if (!start) return nullptr;
    for (unsigned i = 0; i < 256; ++i) {
        const uintptr_t pc = start + i * 4;
        if (!contains(pc, 8, true)) break;
        const uint32_t a = Instruction(pc), b = Instruction(pc + 4);
        if (a == 0xd65f03c0) break;
        // UnityView.handleCommand calls UnitySetKeyState(key, true).
        if (a != 0x52800021 || (b & 0xfc000000) != 0x94000000) continue;
        const uintptr_t target = followBranch(pc + 4 + SignExtend(b & 0x03ffffff, 26) * 4);
        if (!target) continue;
        for (unsigned back = 1; back <= 100 && target >= back * 4; ++back) {
            const uintptr_t candidate = target - back * 4;
            if (!contains(candidate, 4, true)) break;
            // ARM64 STP x20, x19, [sp, #-frame]! prologue used by this engine entry.
            if ((Instruction(candidate) & 0xffc07fff) == 0xa9804ff4) return reinterpret_cast<void*>(candidate);
        }
    }
    return nullptr;
}
} // namespace endplaydesktop
