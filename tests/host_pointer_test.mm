#include "HostPointer.h"
#include "Runtime.h"
#include "InputState.h"

#include <cstdlib>
#include <iostream>

#import <objc/runtime.h>

using namespace endplaydesktop;
extern "C" void EPDTestReset();
extern "C" void EPDTestMouse(MouseState*);

@interface EPDTestHostWindow : NSObject
@property(nonatomic, getter=isKeyWindow) BOOL key;
@end
@implementation EPDTestHostWindow
@end

@interface EPDTestHostApplication : NSObject
@property(nonatomic, getter=isActive) BOOL active;
@property(nonatomic, strong) EPDTestHostWindow* keyWindow;
@end
@implementation EPDTestHostApplication
@end

@interface EPDTestScrollEvent : NSObject
@property(nonatomic) NSInteger type;
@property(nonatomic) BOOL hasPreciseScrollingDeltas;
@property(nonatomic) double deltaX, deltaY, scrollingDeltaX, scrollingDeltaY;
@end
@implementation EPDTestScrollEvent
@end

static EPDTestHostApplication* application;
static id (^event_handler)(id);
static uint64_t event_mask = 0;

static id SharedApplication(__unused id object, __unused SEL selector) { return application; }
static id CaptureMonitor(__unused id object, __unused SEL selector, uint64_t mask, id (^handler)(id))
{
    event_mask = mask;
    event_handler = [handler copy];
    return [NSObject new];
}

static void Require(bool result, const char* message)
{
    if (!result) { std::cerr << message << '\n'; std::exit(1); }
}

static Class HostClass(const char* name)
{
    if (Class klass = objc_getClass(name)) return klass;
    Class klass = objc_allocateClassPair(NSObject.class, name, 0);
    objc_registerClassPair(klass);
    return klass;
}

static MouseState Mouse()
{
    MouseState result;
    EPDTestMouse(&result);
    return result;
}

int main()
{
    @autoreleasepool {
        // Intercept the host's dynamic AppKit entry points only in this isolated
        // test process; no real monitor, application window, or input is created.
        Class event_class = object_getClass(HostClass("NSEvent"));
        Class app_class = object_getClass(HostClass("NSApplication"));
        const SEL add = sel_registerName("addLocalMonitorForEventsMatchingMask:handler:");
        const SEL shared = sel_registerName("sharedApplication");
        IMP saved_add = class_replaceMethod(event_class, add, reinterpret_cast<IMP>(CaptureMonitor), "@@:Q@?");
        IMP saved_shared = class_replaceMethod(app_class, shared, reinterpret_cast<IMP>(SharedApplication), "@@:");

        application = [EPDTestHostApplication new];
        application.active = YES;
        application.keyWindow = [EPDTestHostWindow new];
        application.keyWindow.key = YES;
        EPDTestReset();
        Runtime runtime([] { return application.active; });
        runtime.tick();
        Require(runtime.ready() && !runtime.wantsPointerLock(), "fixture must initialize in an unlocked menu");
        runtime.nativePosition(300, 200);
        Require(InstallHostPointerInput(runtime) && event_handler && (event_mask & (1ull << 22)),
                "the host monitor must include scroll-wheel events");

        EPDTestScrollEvent* event = [EPDTestScrollEvent new];
        event.type = 22;
        event.deltaY = 0.1;
        Require(event_handler(event) == event, "the local monitor must preserve event delivery");
        Require(Mouse().scroll_y == 120 && Mouse().x == 300 && Mouse().y == 519,
                "a host wheel detent must scroll menus at Windows scale without moving the pointer");
        event_handler(event);
        Require([runtime.status()[@"native_scroll_events"] unsignedLongLongValue] == 2,
                "identical consecutive wheel events must not be suppressed");

        event.hasPreciseScrollingDeltas = YES;
        event.scrollingDeltaX = 2.5;
        event.scrollingDeltaY = -7.5;
        event_handler(event);
        Require(Mouse().scroll_x == -30 && Mouse().scroll_y == -90 && Mouse().dx == 0 && Mouse().dy == 0,
                "trackpad events must use precise deltas, preserve fractions, and never become camera motion");

        application.active = NO;
        event_handler(event);
        application.active = YES;
        application.keyWindow.key = NO;
        event_handler(event);
        Require([runtime.status()[@"native_scroll_events"] unsignedLongLongValue] == 3,
                "scrolls outside the active key window must not reach the game");

        if (saved_add) class_replaceMethod(event_class, add, saved_add, "@@:Q@?");
        if (saved_shared) class_replaceMethod(app_class, shared, saved_shared, "@@:");
        event_handler = nil;
        std::cout << "host wheel event routing checks passed\n";
    }
}
