#include "Runtime.h"

#include "InputState.h"
#include "NativeInput.h"
#include "HostPointer.h"

#include <array>
#include <cstring>
#include <mach-o/dyld.h>

#import <GameController/GameController.h>
#import <QuartzCore/QuartzCore.h>
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <os/log.h>

using namespace endplaydesktop;

namespace
{
bool host_pointer_events = false;

UIView* FindUnityView(UIView* root)
{
    if (!root) return nil;
    Class unity = NSClassFromString(@"UnityView");
    if (unity && [root isKindOfClass:unity]) return root;
    for (UIView* child in root.subviews) if (UIView* result = FindUnityView(child)) return result;
    return nil;
}

bool HasConflictingPlugin()
{
    for (uint32_t i = 0; i < _dyld_image_count(); ++i) {
        const char* name = _dyld_get_image_name(i);
        if (name && std::strstr(name, "/libUnityDesktopMode.dylib")) return true;
    }
    return false;
}

void AttachKeyboard(GCKeyboard* keyboard)
{
    keyboard.keyboardInput.keyChangedHandler = ^(GCKeyboardInput*, GCControllerButtonInput*, GCKeyCode code, BOOL pressed) {
        if (const auto vk = HidToWin32Key(static_cast<int>(code))) {
            const int key = *vk;
            dispatch_async(dispatch_get_main_queue(), ^{ GetRuntime().nativeKey(key, pressed); });
        }
    };
}

void AttachMouse(GCMouse* mouse)
{
    GCMouseInput* input = mouse.mouseInput;
    input.mouseMovedHandler = ^(GCMouseInput*, float dx, float dy) {
        if (host_pointer_events) return; // 本应用事件与 GameController 只取一个相对位移来源。
        dispatch_async(dispatch_get_main_queue(), ^{ GetRuntime().nativeDelta(dx, dy); });
    };
    const std::array<GCControllerButtonInput*, 3> buttons { input.leftButton, input.rightButton, input.middleButton };
    for (size_t i = 0; i < buttons.size(); ++i) {
        GCControllerButtonInput* button = buttons[i];
        if (!button) continue;
        button.pressedChangedHandler = ^(GCControllerButtonInput*, float, BOOL down) {
            dispatch_async(dispatch_get_main_queue(), ^{ GetRuntime().nativeButton(static_cast<int>(i), down); });
        };
    }
    input.scroll.valueChangedHandler = ^(GCControllerDirectionPad*, float dx, float dy) {
        if (host_pointer_events) return; // NSEvent 已处理滚轮；GameController 只作回退，避免重复。
        dispatch_async(dispatch_get_main_queue(), ^{ GetRuntime().nativeScroll(dx, dy); });
    };
}

} // namespace

@interface EPDHost : NSObject
@property(nonatomic, strong) CADisplayLink* displayLink;
@property(nonatomic, weak) UIView* unityView;
@property(nonatomic, strong) UIHoverGestureRecognizer* hover;
@property(nonatomic) BOOL conflict;
@property(nonatomic) BOOL inputAttached;
@end

@implementation EPDHost

- (void)start
{
    StartServer();
    self.displayLink = [CADisplayLink displayLinkWithTarget:self selector:@selector(tick:)];
    self.displayLink.preferredFramesPerSecond = 60;
    [self.displayLink addToRunLoop:NSRunLoop.mainRunLoop forMode:NSRunLoopCommonModes];
    [NSNotificationCenter.defaultCenter addObserverForName:UIApplicationWillResignActiveNotification object:nil queue:NSOperationQueue.mainQueue
                   usingBlock:^(__unused NSNotification* event) { ReleaseHostPointerLock(); GetRuntime().nativeReset(); }];
}

- (void)attachInput
{
    // Unity/PlayTools 启动时也设置这些单值回调；在托管运行时就绪后再安装。
    NSNotificationCenter* center = NSNotificationCenter.defaultCenter;
    [center addObserverForName:GCKeyboardDidConnectNotification object:nil queue:NSOperationQueue.mainQueue
                   usingBlock:^(NSNotification* event) { AttachKeyboard(event.object); }];
    [center addObserverForName:GCMouseDidConnectNotification object:nil queue:NSOperationQueue.mainQueue
                   usingBlock:^(NSNotification* event) { AttachMouse(event.object); }];
    if (GCKeyboard.coalescedKeyboard) AttachKeyboard(GCKeyboard.coalescedKeyboard);
    for (GCMouse* mouse in GCMouse.mice) AttachMouse(mouse);
}

- (void)tick:(__unused CADisplayLink*)link
{
    if (!self.conflict && HasConflictingPlugin()) {
        self.conflict = YES;
        GetRuntime().disable("remove libUnityDesktopMode.dylib before using EndPlayDesktop");
        os_log_error(OS_LOG_DEFAULT, "[EndPlayDesktop] conflicting desktop plugin detected; input disabled");
    }
    if (self.conflict) return;
    GetRuntime().tick();
    if (GetRuntime().ready() && !self.inputAttached) {
        self.inputAttached = YES;
        host_pointer_events = InstallHostPointerInput(GetRuntime());
        [self attachInput];
    }
    UpdateHostPointerLock(GetRuntime().wantsPointerLock());
    if (!self.unityView) {
        for (UIScene* scene in UIApplication.sharedApplication.connectedScenes) {
            if (![scene isKindOfClass:UIWindowScene.class]) continue;
            for (UIWindow* window in ((UIWindowScene*)scene).windows) {
                UIView* view = FindUnityView(window.rootViewController.view);
                if (!view) continue;
                self.unityView = view;
                InstallNativeInputHooks(object_getClass(view), GetRuntime());
                self.hover = [[UIHoverGestureRecognizer alloc] initWithTarget:self action:@selector(hover:)];
                self.hover.cancelsTouchesInView = NO;
                [view addGestureRecognizer:self.hover];
                return;
            }
        }
    }
}

- (void)hover:(UIHoverGestureRecognizer*)gesture
{
    UIView* view = self.unityView;
    if (!view || !GetRuntime().ready() || GetRuntime().wantsPointerLock() || view.bounds.size.width <= 0 || view.bounds.size.height <= 0) return;
    const CGPoint point = [gesture locationInView:view];
    UpdateNativePosition(GetRuntime(), view, point);
}

@end

__attribute__((constructor)) static void EndPlayDesktopLoad()
{
    @autoreleasepool {
        if (![NSBundle.mainBundle.bundleIdentifier isEqual:@"com.hypergryph.endfield"]) return;
        dispatch_async(dispatch_get_main_queue(), ^{
            static EPDHost* host;
            host = [EPDHost new];
            [host start];
        });
    }
}
