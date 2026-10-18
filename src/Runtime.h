#pragma once

#import <Foundation/Foundation.h>

#include <memory>
#include <functional>
#include <utility>

namespace endplaydesktop
{

class Runtime
{
public:
    explicit Runtime(std::function<bool()> native_focus = {});
    ~Runtime();
    Runtime(const Runtime&) = delete;
    Runtime& operator=(const Runtime&) = delete;

    void tick();
    NSDictionary* status() const;
    NSDictionary* camera() const;
    NSDictionary* command(NSDictionary* request);
    bool ready() const;
    bool automationActive() const;
    std::pair<int, int> dimensions() const;
    bool wantsPointerLock() const;
    void endSession();
    void disable(const char* reason);
    void nativeReset();
    void nativeKey(int vk, bool down);
    void nativeButton(int button, bool down);
    void nativePosition(float x, float y, bool delta = false);
    void nativeDelta(float dx, float dy);
    // Physical wheel ticks; automation's scroll command uses Windows units (120/tick).
    void nativeScroll(float dx, float dy);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

Runtime& GetRuntime();
void StartServer();

} // namespace endplaydesktop
