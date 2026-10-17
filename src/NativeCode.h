#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace endplaydesktop
{

struct NativeRange { uintptr_t begin, end; bool writable, executable; };

// 只解析当前已加载镜像；不扫描整个地址空间、不改写机器指令。
class NativeCode
{
public:
    explicit NativeCode(const void* address);
    explicit NativeCode(std::vector<NativeRange> ranges);
    void** icallSlot(const void* method, const char* name) const;
    void* keyStateFunction(const void* handle_command) const;
    bool contains(uintptr_t address, size_t size, bool executable = false) const;

private:
    std::vector<NativeRange> ranges_;
    uintptr_t followBranch(uintptr_t address) const;
};

} // namespace endplaydesktop
