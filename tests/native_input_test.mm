#include "NativeInput.h"
#include "Runtime.h"
#include "InputState.h"

#include <cstdlib>
#include <iostream>

using namespace endplaydesktop;
extern "C" void EPDTestReset();
extern "C" bool EPDTestKeyDown(int);
extern "C" void EPDTestMouse(MouseState*);

static int original_events = 0;
@interface EPDTestView : NSObject
@property(nonatomic) CGRect bounds;
- (void)touchesBegan:(NSSet*)touches withEvent:(UIEvent*)event;
- (void)touchesMoved:(NSSet*)touches withEvent:(UIEvent*)event;
- (void)touchesEnded:(NSSet*)touches withEvent:(UIEvent*)event;
- (void)touchesCancelled:(NSSet*)touches withEvent:(UIEvent*)event;
- (void)pressesBegan:(NSSet*)presses withEvent:(UIPressesEvent*)event;
- (void)pressesEnded:(NSSet*)presses withEvent:(UIPressesEvent*)event;
- (void)pressesCancelled:(NSSet*)presses withEvent:(UIPressesEvent*)event;
@end
@implementation EPDTestView
- (void)touchesBegan:(__unused NSSet*)touches withEvent:(__unused UIEvent*)event { ++original_events; }
- (void)touchesMoved:(__unused NSSet*)touches withEvent:(__unused UIEvent*)event { ++original_events; }
- (void)touchesEnded:(__unused NSSet*)touches withEvent:(__unused UIEvent*)event { ++original_events; }
- (void)touchesCancelled:(__unused NSSet*)touches withEvent:(__unused UIEvent*)event { ++original_events; }
- (void)pressesBegan:(__unused NSSet*)presses withEvent:(__unused UIPressesEvent*)event { ++original_events; }
- (void)pressesEnded:(__unused NSSet*)presses withEvent:(__unused UIPressesEvent*)event { ++original_events; }
- (void)pressesCancelled:(__unused NSSet*)presses withEvent:(__unused UIPressesEvent*)event { ++original_events; }
@end
@interface EPDTestTouch : NSObject
@property(nonatomic) UITouchPhase phase;
@property(nonatomic) CGPoint point;
- (CGPoint)locationInView:(UIView*)view;
@end
@implementation EPDTestTouch
- (CGPoint)locationInView:(__unused UIView*)view { return self.point; }
@end
@interface EPDTestEvent : NSObject
@property(nonatomic) UIEventButtonMask buttonMask;
@end
@implementation EPDTestEvent
@end
@interface EPDTestKey : NSObject
@property(nonatomic) UIKeyboardHIDUsage keyCode;
@end
@implementation EPDTestKey
@end
@interface EPDTestPress : NSObject
@property(nonatomic, strong) EPDTestKey* key;
@end
@implementation EPDTestPress
@end

static void Require(bool value, const char* message)
{
    if (!value) { std::cerr << message << '\n'; std::exit(1); }
}
static MouseState Mouse()
{
    MouseState state;
    EPDTestMouse(&state);
    return state;
}

int main()
{
    @autoreleasepool {
        EPDTestReset();
        Runtime runtime([] { return true; });
        EPDTestView* view = [EPDTestView new];
        view.bounds = CGRectMake(0, 0, 640, 360);
        InstallNativeInputHooks(EPDTestView.class, runtime);
        EPDTestTouch* touch = [EPDTestTouch new];
        touch.phase = UITouchPhaseBegan;
        touch.point = CGPointMake(100, 120);
        NSSet* touches = [NSSet setWithObject:touch];
        EPDTestEvent* event = [EPDTestEvent new];
        event.buttonMask = UIEventButtonMaskPrimary;
        [view touchesBegan:touches withEvent:(id)event];
        Require(original_events == 1, "uninitialized plugin must preserve the original Unity touch handler");
        runtime.tick();
        Require(runtime.ready(), "mock runtime must initialize");
        [view touchesBegan:touches withEvent:(id)event];
        Require(Mouse().buttons == 1 && Mouse().x == 200 && Mouse().y == 479, "UIKit click must become a correctly positioned PC mouse-down");
        touch.phase = UITouchPhaseEnded;
        event.buttonMask = 0;
        [view touchesEnded:touches withEvent:(id)event];
        Require(Mouse().buttons == 0 && original_events == 1, "mouse-up must use the remembered button without generating touch UI input");
        runtime.command(@{ @"op": @"begin" });
        touch.phase = UITouchPhaseBegan;
        event.buttonMask = UIEventButtonMaskSecondary;
        [view touchesBegan:touches withEvent:(id)event];
        Require(Mouse().buttons == 2 && runtime.automationActive(), "UIKit right-click must work while keeping the automation session");
        touch.phase = UITouchPhaseCancelled;
        event.buttonMask = 0;
        [view touchesCancelled:touches withEvent:(id)event];
        Require(Mouse().buttons == 0, "cancelled pointer input must release its button");
        EPDTestPress* press = [EPDTestPress new];
        press.key = [EPDTestKey new];
        press.key.keyCode = (UIKeyboardHIDUsage)26;
        NSSet* presses = [NSSet setWithObject:press];
        [view pressesBegan:presses withEvent:nil];
        Require(EPDTestKeyDown(37) && runtime.automationActive(), "UIKit physical key must reach the PC keyboard during automation");
        [view pressesCancelled:presses withEvent:nil];
        Require(!EPDTestKeyDown(37), "cancelled UIKit key must be released");
        runtime.endSession();
        std::cout << "UIKit manual input checks passed\n";
    }
}
