#import <AppKit/AppKit.h>
#include <cassert>
#include <cstdlib>
#include <cstring>

@interface LifecycleDelegate : NSObject <NSApplicationDelegate, NSWindowDelegate>
@property NSWindow* window;
@property NSStatusItem* status;
@property NSUInteger reopens;
@property BOOL manual;
@end

@implementation LifecycleDelegate
- (void)record {
    NSRect frame = self.status.button.window.frame;
    NSDictionary* value = @{
        @"window_visible": @(self.window.isVisible), @"reopens": @(self.reopens),
        @"status_frame": @[@(frame.origin.x), @(frame.origin.y), @(frame.size.width), @(frame.size.height)],
        @"entry": [NSBundle.mainBundle objectForInfoDictionaryKey:@"CFBundleExecutable"]
    };
    NSData* data = [NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingPrettyPrinted error:nil];
    [data writeToFile:[NSBundle.mainBundle.bundlePath stringByAppendingString:@".json"] atomically:YES];
}
- (BOOL)applicationShouldHandleReopen:(NSApplication*)app hasVisibleWindows:(BOOL)visible {
    (void)app;
    ++self.reopens;
    return visible;
}
- (BOOL)windowShouldClose:(NSWindow*)window {
    [window orderOut:nil];
    [self record];
    return NO;
}
- (void)show:(id)sender {
    (void)sender;
    [NSApp.delegate applicationShouldHandleReopen:NSApp hasVisibleWindows:NO];
    [self record];
}
- (void)applicationDidFinishLaunching:(NSNotification*)notification {
    (void)notification;
    assert(getenv("ENDPLAYDESKTOP_ADAPTER_LOADED") && !strcmp(getenv("ENDPLAYDESKTOP_ADAPTER_LOADED"), "1"));
    assert(!getenv("DYLD_INSERT_LIBRARIES"));
    self.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(120, 120, 460, 160)
        styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
        backing:NSBackingStoreBuffered defer:NO];
    self.window.title = @"EndPlayDesktop background regression";
    self.window.delegate = self;
    [self.window makeKeyAndOrderFront:nil];
    self.status = [NSStatusBar.systemStatusBar statusItemWithLength:NSVariableStatusItemLength];
    self.status.button.title = @"EPD test";
    self.status.button.toolTip = @"EndPlayDesktop background regression";
    NSMenu* menu = [NSMenu new];
    NSMenuItem* show = [[NSMenuItem alloc] initWithTitle:@"Show window" action:@selector(show:) keyEquivalent:@""];
    show.target = self;
    [menu addItem:show];
    [menu addItemWithTitle:@"Quit" action:@selector(terminate:) keyEquivalent:@"q"];
    self.status.menu = menu;
    dispatch_async(dispatch_get_main_queue(), ^{
        if (self.manual) {
            [NSTimer scheduledTimerWithTimeInterval:0.5 repeats:YES block:^(NSTimer*) { [self record]; }];
            return;
        }
        assert([NSApp.delegate applicationShouldHandleReopen:NSApp hasVisibleWindows:YES]);
        assert(self.reopens == 1);
        [self.window orderOut:nil];
        assert(!self.window.isVisible);
        assert([NSApp.delegate applicationShouldHandleReopen:NSApp hasVisibleWindows:NO]);
        assert(self.reopens == 2 && self.window.isVisible);
        [NSApp terminate:nil];
    });
}
@end

int main(int argc, char** argv) {
    @autoreleasepool {
        NSApplication* app = NSApplication.sharedApplication;
        LifecycleDelegate* delegate = [LifecycleDelegate new];
        delegate.manual = argc == 2 && !strcmp(argv[1], "--manual");
        app.delegate = delegate;
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        [app run];
    }
}
