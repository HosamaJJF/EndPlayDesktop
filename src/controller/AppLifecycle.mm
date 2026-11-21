// Preserve the upstream delegate and add the standard Dock reopen fallback.
#import <AppKit/AppKit.h>
#import <objc/runtime.h>
#include "AppLifecycle.h"

namespace {
using Reopen = BOOL (*)(id, SEL, NSApplication*, BOOL);
Reopen upstreamReopen = nullptr;

BOOL reopen(id delegate, SEL selector, NSApplication* app, BOOL hasVisibleWindows) {
    BOOL handled = upstreamReopen ? upstreamReopen(delegate, selector, app, hasVisibleWindows) : NO;
    if (!hasVisibleWindows) {
        for (NSWindow* window in app.windows) {
            // canBecomeMainWindow is false while an ordinary NSWindow is hidden.
            if ([window isKindOfClass:NSPanel.class] || window.level != NSNormalWindowLevel ||
                window.isSheet || window.parentWindow ||
                !(window.styleMask & NSWindowStyleMaskTitled)) continue;
            if (window.isMiniaturized) [window deminiaturize:nil];
            [window makeKeyAndOrderFront:nil];
            [app activate];
            return YES;
        }
    }
    return handled;
}
}

void epd::installApplicationLifecycle() {
    // Do not create NSApplication before the upstream GUI initializes it.
    [NSNotificationCenter.defaultCenter addObserverForName:NSApplicationDidFinishLaunchingNotification
        object:nil queue:nil usingBlock:^(NSNotification*) {
            id delegate = NSApp.delegate;
            if (!delegate) return;
            Class type = object_getClass(delegate);
            SEL selector = @selector(applicationShouldHandleReopen:hasVisibleWindows:);
            Method method = class_getInstanceMethod(type, selector);
            if (method && method_getImplementation(method) == reinterpret_cast<IMP>(reopen)) return;
            upstreamReopen = method ? reinterpret_cast<Reopen>(method_getImplementation(method)) : nullptr;
            const char* encoding = method ? method_getTypeEncoding(method) : "B@:@B";
            // Adding on the concrete delegate avoids changing an inherited method
            // for other classes. Forward to upstream before applying the fallback.
            if (!class_addMethod(type, selector, reinterpret_cast<IMP>(reopen), encoding))
                class_replaceMethod(type, selector, reinterpret_cast<IMP>(reopen), encoding);
        }];
}
