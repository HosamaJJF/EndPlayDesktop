#include "NativeInput.h"

#include "InputState.h"
#include "Runtime.h"

#include <array>

#import <objc/runtime.h>

namespace endplaydesktop
{
namespace
{
struct Hook { SEL selector = nullptr; IMP original = nullptr; };
std::array<Hook, 7> hooks;
Runtime* input_runtime = nullptr;
Class installed_class = Nil;
char touch_buttons_key;

void Original(id object, SEL selector, NSSet* values, UIEvent* event)
{
    for (const auto& hook : hooks) {
        if (hook.selector == selector && hook.original) {
            reinterpret_cast<void (*)(id, SEL, NSSet*, UIEvent*)>(hook.original)(object, selector, values, event);
            return;
        }
    }
}

void Touches(id object, SEL selector, NSSet<UITouch*>* touches, UIEvent* event)
{
    if (!input_runtime || !input_runtime->ready()) { Original(object, selector, touches, event); return; }
    // PC 模式仍需抑制 Unity 的触屏输入，但不能吞掉鼠标/触控板转换出的 UIKit 点击。
    // 将它们转成虚拟 Mouse，覆盖 GCMouse 未上报的触控板和 UIKit 鼠标事件。
    for (UITouch* touch in touches) {
        const bool began = touch.phase == UITouchPhaseBegan;
        const bool ended = touch.phase == UITouchPhaseEnded || touch.phase == UITouchPhaseCancelled;
        UpdateNativePosition(*input_runtime, object, [touch locationInView:object], !began && !ended);
        if (began) {
            const NSUInteger buttons = event.buttonMask ?: UIEventButtonMaskPrimary;
            objc_setAssociatedObject(touch, &touch_buttons_key, @(buttons), OBJC_ASSOCIATION_RETAIN_NONATOMIC);
        }
        if (began || ended) {
            NSNumber* stored = objc_getAssociatedObject(touch, &touch_buttons_key);
            const NSUInteger buttons = stored ? stored.unsignedIntegerValue : UIEventButtonMaskPrimary;
            for (int button = 0; button < 5; ++button) {
                if (buttons & (1u << button)) input_runtime->nativeButton(button, began);
            }
            if (ended) objc_setAssociatedObject(touch, &touch_buttons_key, nil, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
        }
    }
}

void Presses(id object, SEL selector, NSSet<UIPress*>* presses, UIPressesEvent* event)
{
    if (!input_runtime || !input_runtime->ready()) { Original(object, selector, presses, event); return; }
    bool keyboard_event = false;
    for (UIPress* press in presses) {
        if (!press.key) continue;
        if (const auto vk = HidToWin32Key(static_cast<int>(press.key.keyCode))) {
            keyboard_event = true;
            input_runtime->nativeKey(*vk, selector == hooks[4].selector);
        }
    }
    if (!keyboard_event) Original(object, selector, presses, event);
}
} // namespace

void UpdateNativePosition(Runtime& runtime, UIView* view, CGPoint point, bool delta)
{
    if (!runtime.ready() || view.bounds.size.width <= 0 || view.bounds.size.height <= 0) return;
    const auto [width, height] = runtime.dimensions();
    runtime.nativePosition(static_cast<float>(point.x / view.bounds.size.width * width),
                           static_cast<float>(point.y / view.bounds.size.height * height), delta);
}

void InstallNativeInputHooks(Class klass, Runtime& runtime)
{
    if (!klass || installed_class) return;
    installed_class = klass;
    input_runtime = &runtime;
    constexpr std::array<const char*, 7> names {
        "touchesBegan:withEvent:", "touchesMoved:withEvent:", "touchesEnded:withEvent:", "touchesCancelled:withEvent:",
        "pressesBegan:withEvent:", "pressesEnded:withEvent:", "pressesCancelled:withEvent:"
    };
    for (size_t i = 0; i < names.size(); ++i) {
        SEL selector = sel_registerName(names[i]);
        Method method = class_getInstanceMethod(klass, selector);
        if (!method) continue;
        hooks[i] = { selector, method_getImplementation(method) };
        IMP replacement = i < 4 ? reinterpret_cast<IMP>(Touches) : reinterpret_cast<IMP>(Presses);
        if (!class_addMethod(klass, selector, replacement, method_getTypeEncoding(method))) method_setImplementation(method, replacement);
    }
}
} // namespace endplaydesktop
