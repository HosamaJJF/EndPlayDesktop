#pragma once

#import <UIKit/UIKit.h>

namespace endplaydesktop
{
class Runtime;
void InstallNativeInputHooks(Class klass, Runtime& runtime);
void UpdateNativePosition(Runtime& runtime, UIView* view, CGPoint point, bool delta = false);
} // namespace endplaydesktop
