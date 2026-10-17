#include "HostPointer.h"
#include "Runtime.h"

#include <dlfcn.h>

#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <objc/message.h>

namespace endplaydesktop
{
namespace
{
bool locked = false;
id monitor;
int (*associate)(bool) = nullptr;
int (*hide)(uint32_t) = nullptr;
int (*show)(uint32_t) = nullptr;
int (*warp)(CGPoint) = nullptr;
uint32_t (*display)() = nullptr;

id Send(id target, const char* name)
{
    return reinterpret_cast<id (*)(id, SEL)>(objc_msgSend)(target, sel_registerName(name));
}
bool Flag(id target, const char* name)
{
    return target && reinterpret_cast<BOOL (*)(id, SEL)>(objc_msgSend)(target, sel_registerName(name));
}
id ActiveWindow()
{
    Class app = NSClassFromString(@"NSApplication");
    id application = app ? Send(app, "sharedApplication") : nil;
    if (!Flag(application, "isActive")) return nil;
    id window = Send(application, "keyWindow");
    return Flag(window, "isKeyWindow") ? window : nil;
}
CGRect Frame(id object)
{
    return reinterpret_cast<CGRect (*)(id, SEL)>(objc_msgSend)(object, sel_registerName("frame"));
}
} // namespace

bool InstallHostPointerInput(Runtime& runtime)
{
    // Mac Catalyst 不直接链接 AppKit；仅监听本应用收到的鼠标事件。
    Class event = NSClassFromString(@"NSEvent");
    SEL add = sel_registerName("addLocalMonitorForEventsMatchingMask:handler:");
    if (!event || ![event respondsToSelector:add]) return false;
    if (monitor) return true;
    constexpr uint64_t mask = (1ull << 5) | (1ull << 6) | (1ull << 7) | (1ull << 27);
    monitor = reinterpret_cast<id (*)(id, SEL, uint64_t, id (^)(id))>(objc_msgSend)(event, add, mask, ^id(id input) {
        if (runtime.wantsPointerLock() && ActiveWindow()) {
            const double dx = reinterpret_cast<double (*)(id, SEL)>(objc_msgSend)(input, sel_registerName("deltaX"));
            const double dy = reinterpret_cast<double (*)(id, SEL)>(objc_msgSend)(input, sel_registerName("deltaY"));
            if (dx || dy) runtime.nativeDelta(static_cast<float>(dx), static_cast<float>(-dy));
        }
        return input;
    });
    void* core = dlopen("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics", RTLD_LAZY);
    if (core) {
        associate = reinterpret_cast<decltype(associate)>(dlsym(core, "CGAssociateMouseAndMouseCursorPosition"));
        hide = reinterpret_cast<decltype(hide)>(dlsym(core, "CGDisplayHideCursor"));
        show = reinterpret_cast<decltype(show)>(dlsym(core, "CGDisplayShowCursor"));
        warp = reinterpret_cast<decltype(warp)>(dlsym(core, "CGWarpMouseCursorPosition"));
        display = reinterpret_cast<decltype(display)>(dlsym(core, "CGMainDisplayID"));
        dlclose(core);
    }
    for (NSString* name in @[ @"NSApplicationDidResignActiveNotification", @"NSWindowDidResignKeyNotification" ]) {
        [NSNotificationCenter.defaultCenter addObserverForName:name object:nil queue:NSOperationQueue.mainQueue usingBlock:^(__unused NSNotification* note) {
            ReleaseHostPointerLock();
        }];
    }
    return monitor != nil;
}

void ReleaseHostPointerLock()
{
    if (!locked) return;
    associate(true);
    show(display());
    locked = false;
}

void UpdateHostPointerLock(bool requested)
{
    id window = requested ? ActiveWindow() : nil;
    if (!window) { ReleaseHostPointerLock(); return; }
    if (locked || !associate || !hide || !show || !display) return;
    // 仅前台重新进入世界时，若光标在窗口外，移到窗口中央以免点击落入其他程序。
    if (warp) {
        const CGPoint point = reinterpret_cast<CGPoint (*)(id, SEL)>(objc_msgSend)(NSClassFromString(@"NSEvent"), sel_registerName("mouseLocation"));
        const CGRect bounds = Frame(window);
        if (!CGRectContainsPoint(bounds, point)) {
            id screens = Send(NSClassFromString(@"NSScreen"), "screens");
            const CGRect main = Frame(Send(screens, "firstObject"));
            warp(CGPointMake(CGRectGetMidX(bounds), CGRectGetMaxY(main) - CGRectGetMidY(bounds)));
        }
    }
    if (associate(false) == 0) {
        hide(display());
        locked = true;
    }
}
bool HostPointerLocked() { return locked; }
} // namespace endplaydesktop
