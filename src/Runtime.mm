#include "Runtime.h"

#include "InputState.h"
#include "FrameDelta.h"
#include "NativeCode.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstring>
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <stdexcept>
#include <string>
#include <vector>

#import <QuartzCore/QuartzCore.h>
#import <objc/message.h>
#import <objc/runtime.h>
#import <os/log.h>

namespace endplaydesktop
{
namespace
{

struct Api
{
    void* (*domain_get)() = nullptr;
    const void** (*domain_get_assemblies)(void*, size_t*) = nullptr;
    const void* (*assembly_get_image)(const void*) = nullptr;
    void* (*class_from_name)(const void*, const char*, const char*) = nullptr;
    void* (*class_get_parent)(void*) = nullptr;
    void* (*class_get_field_from_name)(void*, const char*) = nullptr;
    void (*field_static_get_value)(const void*, void*) = nullptr;
    const void* (*class_get_methods)(void*, void**) = nullptr;
    const char* (*method_get_name)(const void*) = nullptr;
    uint32_t (*method_get_param_count)(const void*) = nullptr;
    const void* (*method_get_param)(const void*, uint32_t) = nullptr;
    char* (*type_get_name)(const void*) = nullptr;
    void* (*runtime_invoke)(const void*, void*, void**, void**) = nullptr;
    void* (*object_unbox)(void*) = nullptr;
    void* (*object_get_class)(void*) = nullptr;
    void* (*string_new)(const char*) = nullptr;
    int32_t (*string_length)(void*) = nullptr;
    const uint16_t* (*string_chars)(void*) = nullptr;
    uint32_t (*gchandle_new)(void*, bool) = nullptr;
    void* (*gchandle_get_target)(uint32_t) = nullptr;
    void (*gchandle_free)(uint32_t) = nullptr;
    void (*free)(void*) = nullptr;
    void* (*thread_attach)(void*) = nullptr;
    bool (*is_vm_thread)(void*) = nullptr;
    void (*format_exception)(void*, char*, int) = nullptr;
    void (*legacy_key)(int, bool) = nullptr;

    bool bind()
    {
        void* module = nullptr;
        for (uint32_t i = 0; i < _dyld_image_count(); ++i) {
            const char* name = _dyld_get_image_name(i);
            if (name && std::string(name).ends_with("/UnityFramework.framework/UnityFramework")) {
                module = dlopen(name, RTLD_LAZY | RTLD_NOLOAD);
                break;
            }
        }
        if (!module) return false;
#define EPD_API(name) name = reinterpret_cast<decltype(name)>(dlsym(module, "il2cpp_" #name)); if (!name) { dlclose(module); return false; }
        EPD_API(domain_get)
        EPD_API(domain_get_assemblies)
        EPD_API(assembly_get_image)
        EPD_API(class_from_name)
        EPD_API(class_get_parent)
        EPD_API(class_get_field_from_name)
        EPD_API(field_static_get_value)
        EPD_API(class_get_methods)
        EPD_API(method_get_name)
        EPD_API(method_get_param_count)
        EPD_API(method_get_param)
        EPD_API(type_get_name)
        EPD_API(runtime_invoke)
        EPD_API(object_unbox)
        EPD_API(object_get_class)
        EPD_API(string_new)
        EPD_API(gchandle_new)
        EPD_API(gchandle_get_target)
        EPD_API(gchandle_free)
        EPD_API(free)
        EPD_API(thread_attach)
#undef EPD_API
        format_exception = reinterpret_cast<decltype(format_exception)>(dlsym(module, "il2cpp_format_exception"));
        legacy_key = reinterpret_cast<decltype(legacy_key)>(dlsym(module, "UnitySetKeyState"));
        string_length = reinterpret_cast<decltype(string_length)>(dlsym(module, "il2cpp_string_length"));
        string_chars = reinterpret_cast<decltype(string_chars)>(dlsym(module, "il2cpp_string_chars"));
        dlclose(module);
        return true;
    }

    void* findClass(const char* space, const char* name) const
    {
        size_t count = 0;
        const void** assemblies = domain_get_assemblies(domain_get(), &count);
        for (size_t i = 0; i < count; ++i) {
            if (void* klass = class_from_name(assembly_get_image(assemblies[i]), space, name)) return klass;
        }
        return nullptr;
    }

    const void* method(void* klass, const char* name, std::initializer_list<const char*> params) const
    {
        for (; klass; klass = class_get_parent(klass)) {
            void* iterator = nullptr;
            while (const void* method_info = class_get_methods(klass, &iterator)) {
                if (std::strcmp(method_get_name(method_info), name) != 0 || method_get_param_count(method_info) != params.size()) continue;
                bool match = true;
                uint32_t index = 0;
                for (const char* expected : params) {
                    char* actual = type_get_name(method_get_param(method_info, index++));
                    match = match && actual && std::strcmp(actual, expected) == 0;
                    if (actual) free(actual);
                }
                if (match) return method_info;
            }
        }
        throw std::runtime_error(std::string("managed method unavailable: ") + name);
    }

    void* invoke(const void* method_info, void* object = nullptr, std::initializer_list<void*> args = {}) const
    {
        std::vector<void*> params(args);
        void* exception = nullptr;
        void* value = runtime_invoke(method_info, object, params.empty() ? nullptr : params.data(), &exception);
        if (exception) {
            std::array<char, 1024> message {};
            if (format_exception) format_exception(exception, message.data(), static_cast<int>(message.size()));
            throw std::runtime_error(message[0] ? message.data() : "managed invocation failed");
        }
        return value;
    }

    template <typename T>
    T value(const void* method_info, void* object = nullptr) const
    {
        void* boxed = invoke(method_info, object);
        if (!boxed) throw std::runtime_error("managed getter returned null");
        T result;
        std::memcpy(&result, object_unbox(boxed), sizeof(result));
        return result;
    }
};

class LegacyBridge
{
public:
    explicit LegacyBridge(Api& api) : api_(api) {}
    ~LegacyBridge()
    {
        for (const auto& hook : hooks_) if (*hook.slot == hook.replacement) *hook.slot = hook.original;
        if (instance_ == this) instance_ = nullptr;
    }
    void initialize()
    {
        void* input = api_.findClass("UnityEngine", "Input");
        if (!input) return; // 模拟框架和未启用 Legacy 的客户端没有该类。
        frame_count_ = api_.method(api_.findClass("UnityEngine", "Time"), "get_frameCount", {});
        if (!api_.string_length || !api_.string_chars) throw std::runtime_error("Legacy string APIs unavailable");
        if (!api_.legacy_key) {
            Method command = class_getInstanceMethod(NSClassFromString(@"UnityView"), sel_registerName("handleCommand:"));
            if (command) {
                const auto entry = method_getImplementation(command);
                api_.legacy_key = reinterpret_cast<decltype(api_.legacy_key)>(NativeCode(reinterpret_cast<void*>(entry)).keyStateFunction(reinterpret_cast<void*>(entry)));
            }
        }
        if (!api_.legacy_key) throw std::runtime_error("Legacy UnitySetKeyState entry unavailable");
        instance_ = this;
        auto install = [&](void* klass, const char* method_name, const char* icall, void* replacement,
                           std::initializer_list<const char*> params = {}, std::initializer_list<void*> arguments = {}) -> void* {
            const void* method = api_.method(klass, method_name, params);
            void* entry = *static_cast<void* const*>(method);
            NativeCode code(entry);
            void** slot = code.icallSlot(entry, icall);
            if (!slot) throw std::runtime_error(std::string("Legacy icall layout unavailable: ") + method_name);
            // 先走托管包装以解析 Unity 原始 icall，随后只替换缓存指针。
            if (!*slot) {
                api_.invoke(method, nullptr, arguments);
            }
            void* original = *slot;
            if (!original) throw std::runtime_error(std::string("Legacy icall is null: ") + method_name);
            hooks_.push_back({ slot, original, replacement });
            *slot = replacement;
            return original;
        };
        axis_ = reinterpret_cast<Axis>(install(input, "GetAxis", "UnityEngine.Input::GetAxis(System.String)", reinterpret_cast<void*>(AxisValue), { "System.String" }, { api_.string_new("") }));
        raw_axis_ = reinterpret_cast<Axis>(install(input, "GetAxisRaw", "UnityEngine.Input::GetAxisRaw(System.String)", reinterpret_cast<void*>(RawAxisValue), { "System.String" }, { api_.string_new("") }));
        install(input, "get_mousePresent", "UnityEngine.Input::get_mousePresent()", reinterpret_cast<void*>(MousePresent));
        install(input, "get_mousePosition", "UnityEngine.Input::get_mousePosition_Injected(UnityEngine.Vector3&)", reinterpret_cast<void*>(MousePosition));
        install(input, "get_mouseScrollDelta", "UnityEngine.Input::get_mouseScrollDelta_Injected(UnityEngine.Vector2&)", reinterpret_cast<void*>(MouseScroll));
        void* cursor = api_.findClass("UnityEngine", "Cursor");
        bool visible = true;
        install(cursor, "set_visible", "UnityEngine.Cursor::set_visible(System.Boolean)", reinterpret_cast<void*>(SetVisible), { "System.Boolean" }, { &visible });
        install(cursor, "get_visible", "UnityEngine.Cursor::get_visible()", reinterpret_cast<void*>(GetVisible));
        install(cursor, "get_lockState", "UnityEngine.Cursor::get_lockState()", reinterpret_cast<void*>(GetLockState));
        ready_ = true;
    }
    void update(const MouseState& state, bool automated)
    {
        state_.x = state.x; state_.y = state.y;
        if (!ready_) return;
        if (state.dx || state.dy) {
            if (automated) automated_delta_.add(state.dx, state.dy, frame());
            else { state_.dx = state.dx; state_.dy = state.dy; delta_deadline_ = CACurrentMediaTime() + 0.05; }
        }
        if (state.scroll_x || state.scroll_y) { state_.scroll_x = state.scroll_x; state_.scroll_y = state.scroll_y; scroll_deadline_ = CACurrentMediaTime() + 0.05; }
    }
    void resetDelta() { state_.dx = state_.dy = state_.scroll_x = state_.scroll_y = 0; automated_delta_.reset(); }
    bool ready() const { return ready_; }
    uint64_t reads() const { return reads_.load(); }
    bool wantsPointerLock() const { return !visible_; }

private:
    struct Hook { void** slot; void* original; void* replacement; };
    struct Vector2 { float x, y; };
    struct Vector3 { float x, y, z; };
    using Axis = float (*)(void*);
    Api& api_;
    std::vector<Hook> hooks_;
    MouseState state_;
    FrameDelta automated_delta_;
    const void* frame_count_ = nullptr;
    double delta_deadline_ = 0, scroll_deadline_ = 0;
    bool ready_ = false, visible_ = true;
    Axis axis_ = nullptr, raw_axis_ = nullptr;
    std::atomic<uint64_t> reads_ { 0 };
    inline static LegacyBridge* instance_ = nullptr;
    uint32_t frame() const { return api_.value<uint32_t>(frame_count_); }
    bool named(void* string, const char* name) const
    {
        const int32_t length = api_.string_length(string);
        if (length != static_cast<int32_t>(std::strlen(name))) return false;
        const auto* chars = api_.string_chars(string);
        for (int32_t i = 0; i < length; ++i) if (chars[i] != static_cast<uint8_t>(name[i])) return false;
        return true;
    }
    static float ReadAxis(void* string, bool raw)
    {
        auto& s = *instance_;
        ++s.reads_;
        if (string && (s.named(string, "MouseAxis1") || s.named(string, "Mouse X"))) {
            return s.automated_delta_.read(s.frame()).first + (CACurrentMediaTime() <= s.delta_deadline_ ? s.state_.dx : 0);
        }
        if (string && (s.named(string, "MouseAxis2") || s.named(string, "Mouse Y"))) {
            return s.automated_delta_.read(s.frame()).second + (CACurrentMediaTime() <= s.delta_deadline_ ? s.state_.dy : 0);
        }
        const Axis original = raw ? s.raw_axis_ : s.axis_;
        return original ? original(string) : 0;
    }
    static float AxisValue(void* string) { return ReadAxis(string, false); }
    static float RawAxisValue(void* string) { return ReadAxis(string, true); }
    static bool MousePresent() { ++instance_->reads_; return true; }
    static void MousePosition(Vector3* point) { ++instance_->reads_; *point = { instance_->state_.x, instance_->state_.y, 0 }; }
    static void MouseScroll(Vector2* point)
    {
        ++instance_->reads_;
        *point = CACurrentMediaTime() <= instance_->scroll_deadline_ ? Vector2 { instance_->state_.scroll_x, instance_->state_.scroll_y } : Vector2 {};
    }
    static void SetVisible(bool visible) { instance_->visible_ = visible; }
    static bool GetVisible() { return instance_->visible_; }
    static int GetLockState() { return instance_->visible_ ? 0 : 1; }
};


NSDictionary* Error(const std::string& message)
{
    return @{ @"ok": @NO, @"error": [NSString stringWithUTF8String:message.c_str()] ?: @"runtime error" };
}

id NativeApplicationActive()
{
    // Mac Catalyst 不直接链接 AppKit，通过其公开 Objective-C 接口读取宿主焦点。
    Class klass = NSClassFromString(@"NSApplication");
    SEL shared = NSSelectorFromString(@"sharedApplication"), active = NSSelectorFromString(@"isActive");
    if (!klass || ![klass respondsToSelector:shared]) return NSNull.null;
    id application = reinterpret_cast<id (*)(id, SEL)>(objc_msgSend)(klass, shared);
    if (![application respondsToSelector:active]) return NSNull.null;
    return @(reinterpret_cast<BOOL (*)(id, SEL)>(objc_msgSend)(application, active));
}

double Number(NSDictionary* request, NSString* name, double minimum, double maximum)
{
    id item = request[name];
    if (![item isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)item) == CFBooleanGetTypeID()) {
        throw std::invalid_argument(std::string("numeric field required: ") + name.UTF8String);
    }
    const double value = [item doubleValue];
    if (!std::isfinite(value) || value < minimum || value > maximum) throw std::invalid_argument("numeric field outside range");
    return value;
}

int Integer(NSDictionary* request, NSString* name, int minimum, int maximum)
{
    const double value = Number(request, name, minimum, maximum);
    if (std::trunc(value) != value) throw std::invalid_argument("integer field required");
    return static_cast<int>(value);
}

bool Boolean(NSDictionary* request, NSString* name)
{
    id item = request[name];
    if (!item || CFGetTypeID((__bridge CFTypeRef)item) != CFBooleanGetTypeID()) throw std::invalid_argument("boolean field required");
    return [item boolValue];
}

} // namespace

struct Runtime::Impl
{
    Api api;
    bool bound = false, initialized = false, fatal = false, active = false;
    bool saved_background = false;
    int saved_focus = 0, width = 0, height = 0;
    double last_attempt = -1;
    uint64_t ticks = 0;
    std::string error = "waiting for UnityFramework";
    const void *get_input = nullptr, *set_input = nullptr, *set_platform = nullptr;
    const void *get_width = nullptr, *get_height = nullptr, *queue_event = nullptr;
    const void *get_time = nullptr, *get_update_count = nullptr, *get_background = nullptr, *set_background = nullptr, *get_focused = nullptr;
    const void *get_focus = nullptr, *set_focus = nullptr, *enable_device = nullptr, *remove_device = nullptr;
    const void *mouse_position = nullptr, *mouse_left = nullptr, *keyboard_key = nullptr;
    uint32_t runtime_handle = 0, settings_handle = 0, keyboard_handle = 0, mouse_handle = 0, manager_handle = 0;
    uint32_t queue_target = 0;
    const void* update_count_field = nullptr;
    uint16_t keyboard_id = 0, mouse_id = 0;
    std::vector<uint8_t> keyboard;
    size_t mouse_size = 0;
    MouseState mouse;
    std::array<bool, 256> held {}, native_held {};
    uint16_t automated_buttons = 0, native_buttons = 0;
    uint64_t native_key_events = 0, native_button_events = 0, native_delta_events = 0;
    std::function<bool()> native_focus;
    int last_key = -1;
    std::unique_ptr<LegacyBridge> legacy;

    void* target(uint32_t handle) const
    {
        void* object = api.gchandle_get_target(handle);
        if (!object) throw std::runtime_error("managed object no longer exists");
        return object;
    }

    bool initialize()
    {
        if (!bound) bound = api.bind();
        if (!bound || !api.domain_get()) return false;
        // UIKit 主线程也是 Unity 的执行线程。附加后不分离，避免使引擎自己的线程失效。
        api.thread_attach(api.domain_get());
        void* info = api.findClass("Beyond", "DeviceInfo");
        void* system = api.findClass("UnityEngine.InputSystem", "InputSystem");
        void* screen = api.findClass("UnityEngine", "Screen");
        void* input_runtime = api.findClass("UnityEngine.InputSystem.LowLevel", "NativeInputRuntime");
        if (!info || !system || !screen || !input_runtime) {
            error = "waiting for Endfield managed assemblies";
            return false;
        }
        get_input = api.method(info, "get_inputType", {});
        set_input = api.method(info, "set_inputType", { "Beyond.DeviceInfo.InputType" });
        set_platform = api.method(info, "set_platform", { "UnityEngine.RuntimePlatform" });
        get_width = api.method(screen, "get_width", {});
        get_height = api.method(screen, "get_height", {});
        width = api.value<int>(get_width);
        height = api.value<int>(get_height);
        if (width <= 0 || height <= 0) return false;

        const void* settings = api.method(system, "get_settings", {});
        void* settings_object = api.invoke(settings);
        if (!settings_object) { error = "waiting for Input System initialization"; return false; }
        settings_handle = api.gchandle_new(settings_object, false);
        void* settings_class = api.object_get_class(settings_object);
        get_focus = api.method(settings_class, "get_backgroundBehavior", {});
        set_focus = api.method(settings_class, "set_backgroundBehavior", { "UnityEngine.InputSystem.InputSettings.BackgroundBehavior" });
        void* application = api.findClass("UnityEngine", "Application");
        get_background = api.method(application, "get_runInBackground", {});
        set_background = api.method(application, "set_runInBackground", { "System.Boolean" });
        auto optional_method = [&](void* klass, const char* name, std::initializer_list<const char*> params) -> const void* {
            try { return api.method(klass, name, params); } catch (const std::runtime_error&) { return nullptr; }
        };
        get_focused = optional_method(application, "get_isFocused", {});
        // 高裁剪客户端可能不保留公开包装方法，但 InputManager 的实际执行方法仍在使用。
        void* manager = nullptr;
        if (const void* field = api.class_get_field_from_name(system, "s_Manager")) api.field_static_get_value(field, &manager);
        if (manager) manager_handle = api.gchandle_new(manager, false);
        queue_event = optional_method(system, "QueueEvent", { "UnityEngine.InputSystem.LowLevel.InputEvent*" });
        if (!queue_event && manager) {
            queue_event = api.method(api.object_get_class(manager), "QueueEvent", { "UnityEngine.InputSystem.LowLevel.InputEvent*" });
            queue_target = manager_handle;
        }
        if (!queue_event) throw std::runtime_error("Input System QueueEvent unavailable");
        enable_device = api.method(system, "EnableDevice", { "UnityEngine.InputSystem.InputDevice" });
        remove_device = api.method(system, "RemoveDevice", { "UnityEngine.InputSystem.InputDevice" });
        get_update_count = optional_method(api.findClass("UnityEngine.InputSystem.LowLevel", "InputState"), "get_updateCount", {});
        if (!get_update_count) {
            void* update_class = api.findClass("UnityEngine.InputSystem.LowLevel", "InputUpdate");
            if (update_class) update_count_field = api.class_get_field_from_name(update_class, "s_UpdateStepCount");
            if (!update_count_field) throw std::runtime_error("Input System update counter unavailable");
        }
        void* runtime = nullptr;
        if (const void* getter = optional_method(input_runtime, "get_instance", {})) runtime = api.invoke(getter);
        // Input System 旧版本使用静态 instance 字段，新版本可能裁剪掉单例 getter。
        for (const char* name : { "s_Instance", "instance" }) {
            if (runtime) break;
            if (const void* field = api.class_get_field_from_name(input_runtime, name)) api.field_static_get_value(field, &runtime);
        }
        if (!runtime) throw std::runtime_error("Input runtime is null");
        runtime_handle = api.gchandle_new(runtime, false);
        get_time = api.method(api.object_get_class(runtime), "get_currentTime", {});

        const void* add_device = optional_method(system, "AddDevice", { "System.String", "System.String", "System.String" });
        bool manager_add = false;
        if (!add_device && manager) {
            add_device = api.method(api.object_get_class(manager), "AddDevice", { "System.String", "System.String", "UnityEngine.InputSystem.Utilities.InternedString" });
            manager_add = true;
        }
        if (!add_device) throw std::runtime_error("Input System AddDevice unavailable");
        auto create_device = [&](const char* layout, const char* name, uint32_t& handle, uint16_t& id, uint32_t format) {
            // InternedString 是两个托管 string 引用；全零表示默认 variants。
            std::array<void*, 2> variants {};
            void* device = api.invoke(add_device, manager_add ? target(manager_handle) : nullptr,
                                     { api.string_new(layout), api.string_new(name), manager_add ? variants.data() : nullptr });
            if (!device) throw std::runtime_error("AddDevice returned null");
            handle = api.gchandle_new(device, false);
            void* klass = api.object_get_class(device);
            const int raw_id = api.value<int>(api.method(klass, "get_deviceId", {}), device);
            if (raw_id < 1 || raw_id > UINT16_MAX) throw std::runtime_error("Input device ID outside event range");
            id = static_cast<uint16_t>(raw_id);
            struct StateBlock { uint32_t format, byte_offset, bit_offset, size_bits; };
            const auto block = api.value<StateBlock>(api.method(klass, "get_stateBlock", {}), device);
            if (block.format != format || block.bit_offset != 0 || block.size_bits > 4096) {
                throw std::runtime_error(std::string("unsupported Input System state layout: ") + layout
                                         + " format=" + std::to_string(block.format) + " expected=" + std::to_string(format)
                                         + " bit_offset=" + std::to_string(block.bit_offset) + " size_bits=" + std::to_string(block.size_bits));
            }
            return static_cast<size_t>((block.size_bits + 7) / 8);
        };
        keyboard.resize(create_device("Keyboard", "EndPlayDesktopKeyboard", keyboard_handle, keyboard_id, FourCC('K', 'E', 'Y', 'S')));
        mouse_size = create_device("Mouse", "EndPlayDesktopMouse", mouse_handle, mouse_id, FourCC('M', 'O', 'U', 'S'));
        mouse_position = optional_method(api.object_get_class(target(mouse_handle)), "get_position", {});
        mouse_left = optional_method(api.object_get_class(target(mouse_handle)), "get_leftButton", {});
        keyboard_key = optional_method(api.object_get_class(target(keyboard_handle)), "get_Item", { "UnityEngine.InputSystem.Key" });
        if (keyboard.size() < 14 || mouse_size < sizeof(MouseState)) throw std::runtime_error("Input System state buffer too small");
        mouse.x = width / 2.0f;
        mouse.y = height / 2.0f;
        legacy = std::make_unique<LegacyBridge>(api);
        legacy->initialize();
        legacy->update(mouse, false);
        desktopMode();
        initialized = true;
        error.clear();
        os_log_info(OS_LOG_DEFAULT, "[EndPlayDesktop] PC mode ready, %d x %d", width, height);
        return true;
    }

    void desktopMode()
    {
        int platform = 2, input = 0;
        api.invoke(set_platform, nullptr, { &platform });
        api.invoke(set_input, nullptr, { &input });
    }

    void queue(uint16_t id, uint32_t format, const void* data, size_t size)
    {
        auto packet = MakeStateEvent(id, format, api.value<double>(get_time, target(runtime_handle)), data, size);
        // IL2CPP 的指针参数直接放入 params[]，不同于普通值类型的地址传参。
        api.invoke(queue_event, queue_target ? target(queue_target) : nullptr, { packet.data() });
    }

    uint32_t updateCount() const
    {
        if (get_update_count) return api.value<uint32_t>(get_update_count);
        uint32_t result = 0;
        api.field_static_get_value(update_count_field, &result);
        return result;
    }

    void queueKeyboard() { queue(keyboard_id, FourCC('K', 'E', 'Y', 'S'), keyboard.data(), keyboard.size()); }

    NSDictionary* readback() const
    {
        if (!mouse_position || !mouse_left || !keyboard_key) return @{ @"available": @NO };
        try {
            void* position = api.invoke(mouse_position, target(mouse_handle));
            struct Vector2 { float x, y; };
            const auto point = api.value<Vector2>(api.method(api.object_get_class(position), "ReadValue", {}), position);
            void* left = api.invoke(mouse_left, target(mouse_handle));
            const bool pressed = api.value<bool>(api.method(api.object_get_class(left), "get_isPressed", {}), left);
            id key_pressed = NSNull.null;
            if (const auto key = Win32ToUnityKey(last_key)) {
                int index = *key;
                void* control = api.invoke(keyboard_key, target(keyboard_handle), { &index });
                key_pressed = @(api.value<bool>(api.method(api.object_get_class(control), "get_isPressed", {}), control));
            }
            return @{ @"available": @YES, @"mouse_x": @(point.x), @"mouse_y": @(point.y), @"left_pressed": @(pressed),
                      @"last_key_vk": @(last_key), @"last_key_pressed": key_pressed };
        } catch (const std::exception& e) { return @{ @"available": @NO, @"error": [NSString stringWithUTF8String:e.what()] ?: @"readback failed" }; }
    }
    void queueMouse(bool automated = false)
    {
        if (automated) NormalizeDesktopDelta(mouse, width, height);
        if (legacy) legacy->update(mouse, automated);
        std::vector<uint8_t> data(mouse_size);
        std::memcpy(data.data(), &mouse, sizeof(mouse));
        queue(mouse_id, FourCC('M', 'O', 'U', 'S'), data.data(), data.size());
        mouse.dx = mouse.dy = mouse.scroll_x = mouse.scroll_y = 0;
    }

    void key(int vk, bool down, bool physical = false)
    {
        const auto index = Win32ToUnityKey(vk);
        if (!index || static_cast<size_t>(*index / 8) >= keyboard.size()) throw std::invalid_argument("unsupported Win32 VK");
        last_key = vk;
        auto& source = physical ? native_held : held;
        if (source[vk] == down) return;
        const uint8_t mask = static_cast<uint8_t>(1 << (*index % 8));
        const bool previous = (keyboard[*index / 8] & mask) != 0;
        source[vk] = down;
        // 两个来源独立持键；通用修饰键与左右键可能映射到同一个 Unity 位。
        bool effective = false;
        for (size_t code = 0; code < held.size(); ++code) {
            if ((held[code] || native_held[code]) && Win32ToUnityKey(static_cast<int>(code)) == index) {
                effective = true;
                break;
            }
        }
        if (effective) keyboard[*index / 8] |= mask;
        else keyboard[*index / 8] &= static_cast<uint8_t>(~mask);
        if (previous != effective) {
            if (const auto code = Win32ToLegacyKey(vk)) {
                if (api.legacy_key) api.legacy_key(*code, effective);
            }
        }
        queueKeyboard();
    }

    void position(float x, float y, bool delta, bool physical = false)
    {
        const float new_x = std::clamp(x, 0.0f, static_cast<float>(width - 1));
        const float new_y = height - 1 - std::clamp(y, 0.0f, static_cast<float>(height - 1));
        mouse.dx = delta ? new_x - mouse.x : 0;
        mouse.dy = delta ? new_y - mouse.y : 0;
        mouse.x = new_x;
        mouse.y = new_y;
        queueMouse(!physical);
    }

    void button(int button, bool down, bool physical = false)
    {
        if (button < 0 || button > 4) throw std::invalid_argument("unsupported mouse button");
        const uint16_t mask = static_cast<uint16_t>(1 << button);
        auto& source = physical ? native_buttons : automated_buttons;
        if (static_cast<bool>(source & mask) == down) return;
        const bool previous = (mouse.buttons & mask) != 0;
        if (down) source |= mask;
        else source &= static_cast<uint16_t>(~mask);
        mouse.buttons = automated_buttons | native_buttons;
        const bool effective = (mouse.buttons & mask) != 0;
        if (previous != effective) {
            if (api.legacy_key) api.legacy_key(323 + button, effective);
        }
        queueMouse();
    }

    void release(bool physical = false)
    {
        if (!initialized) return;
        auto& source = physical ? native_held : held;
        for (size_t vk = 0; vk < source.size(); ++vk) if (source[vk]) key(static_cast<int>(vk), false, physical);
        for (int i = 0; i < 5; ++i) if ((physical ? native_buttons : automated_buttons) & (1 << i)) button(i, false, physical);
        mouse.dx = mouse.dy = mouse.scroll_x = mouse.scroll_y = 0;
        if (legacy) legacy->resetDelta();
        queueKeyboard();
        queueMouse();
    }

    void begin()
    {
        if (active) throw std::runtime_error("automation session already active");
        saved_focus = api.value<int>(get_focus, target(settings_handle));
        saved_background = api.value<bool>(get_background);
        active = true; // 后续任一步失败均由 endSession 恢复已保存的设置。
        bool background = true;
        int ignore_focus = 2;
        api.invoke(set_background, nullptr, { &background });
        api.invoke(set_focus, target(settings_handle), { &ignore_focus });
        api.invoke(enable_device, nullptr, { target(keyboard_handle) });
        api.invoke(enable_device, nullptr, { target(mouse_handle) });
        release();
    }

    void cleanupDevices()
    {
        legacy.reset();
        for (uint32_t* handle : { &keyboard_handle, &mouse_handle, &runtime_handle, &settings_handle, &manager_handle }) {
            if (*handle) {
                if ((handle == &keyboard_handle || handle == &mouse_handle) && remove_device) {
                    try { api.invoke(remove_device, nullptr, { target(*handle) }); } catch (...) {}
                }
                api.gchandle_free(*handle);
                *handle = 0;
            }
        }
    }
};

Runtime::Runtime(std::function<bool()> native_focus) : impl_(std::make_unique<Impl>())
{
    impl_->native_focus = native_focus ? std::move(native_focus) : [] { return [NativeApplicationActive() isEqual:@YES]; };
}
Runtime::~Runtime() = default;
Runtime& GetRuntime() { static Runtime* runtime = new Runtime; return *runtime; }
bool Runtime::ready() const { return impl_->initialized && !impl_->fatal; }
bool Runtime::automationActive() const { return impl_->active; }
std::pair<int, int> Runtime::dimensions() const { return { impl_->width, impl_->height }; }
bool Runtime::wantsPointerLock() const { return ready() && impl_->legacy && impl_->legacy->wantsPointerLock(); }

void Runtime::tick()
{
    auto& s = *impl_;
    ++s.ticks;
    if (s.fatal) return;
    try {
        if (!s.initialized) {
            if (CACurrentMediaTime() - s.last_attempt < 1) return;
            s.last_attempt = CACurrentMediaTime();
            s.initialize();
            return;
        }
        s.width = s.api.value<int>(s.get_width);
        s.height = s.api.value<int>(s.get_height);
        if (s.width <= 0 || s.height <= 0) throw std::runtime_error("invalid game render resolution");
        if (s.api.value<int>(s.get_input) == 1) s.desktopMode();
    } catch (const std::exception& exception) {
        s.error = exception.what();
        os_log_error(OS_LOG_DEFAULT, "[EndPlayDesktop] runtime failed: %{public}s", s.error.c_str());
        endSession();
        if (!s.initialized) s.cleanupDevices();
        s.fatal = true;
    }
}

NSDictionary* Runtime::status() const
{
    const auto& s = *impl_;
    uint32_t updates = 0;
    id focused = NSNull.null, input_type = NSNull.null, background = NSNull.null, behavior = NSNull.null;
    if (ready()) {
        try {
            updates = s.updateCount();
            if (s.get_focused) focused = @(s.api.value<bool>(s.get_focused));
            input_type = @(s.api.value<int>(s.get_input));
            background = @(s.api.value<bool>(s.get_background));
            behavior = @(s.api.value<int>(s.get_focus, s.target(s.settings_handle)));
        }
        catch (const std::exception& e) { return Error(e.what()); }
    }
    return @{ @"ok": @YES, @"protocol": @1, @"plugin": @"EndPlayDesktop", @"version": @"0.1.7",
              @"relative_delta_mode": @"win32_scaled_single_frame",
              @"ready": @(ready()), @"automation": @(s.active), @"width": @(s.width), @"height": @(s.height),
              @"ticks": @(s.ticks), @"input_update_count": @(updates), @"keycode": @"win32_vk",
              @"legacy_keyboard": @(s.api.legacy_key != nullptr), @"legacy_mouse_axes": @(s.legacy && s.legacy->ready()),
              @"legacy_input_reads": @(s.legacy ? s.legacy->reads() : 0),
              @"cursor_lock_requested": @(wantsPointerLock()), @"native_delta_events": @(s.native_delta_events),
              @"focused": focused, @"input_type": input_type, @"run_in_background": background, @"background_behavior": behavior,
              @"native_app_active": NativeApplicationActive(),
              @"native_key_events": @(s.native_key_events), @"native_button_events": @(s.native_button_events),
              @"device_state": ready() ? s.readback() : @{ @"available": @NO },
              @"error": [NSString stringWithUTF8String:s.error.c_str()] ?: @"" };
}

NSDictionary* Runtime::camera() const
{
    if (!ready()) return Error("runtime is not ready");
    try {
        const auto& api = impl_->api;
        void* klass = api.findClass("UnityEngine", "Camera");
        void* camera = api.invoke(api.method(klass, "get_main", {}));
        if (!camera) return @{ @"ok": @YES, @"available": @NO, @"error": @"main camera unavailable" };
        void* transform = api.invoke(api.method(klass, "get_transform", {}), camera);
        if (!transform) return @{ @"ok": @YES, @"available": @NO, @"error": @"camera transform unavailable" };
        struct Vector3 { float x, y, z; };
        const auto euler = api.value<Vector3>(api.method(api.object_get_class(transform), "get_eulerAngles", {}), transform);
        const float pitch = euler.x > 180 ? 360 - euler.x : -euler.x;
        return @{ @"ok": @YES, @"available": @YES, @"pitch_degrees": @(pitch), @"yaw_degrees": @(euler.y),
                  @"field_of_view": @(api.value<float>(api.method(klass, "get_fieldOfView", {}), camera)) };
    } catch (const std::exception& e) {
        return @{ @"ok": @YES, @"available": @NO, @"error": [NSString stringWithUTF8String:e.what()] ?: @"camera query failed" };
    }
}

void Runtime::endSession()
{
    auto& s = *impl_;
    if (!s.active) return;
    try { s.release(); } catch (const std::exception& e) { os_log_error(OS_LOG_DEFAULT, "[EndPlayDesktop] release failed: %{public}s", e.what()); }
    try { s.api.invoke(s.set_focus, s.target(s.settings_handle), { &s.saved_focus }); }
    catch (const std::exception& e) { os_log_error(OS_LOG_DEFAULT, "[EndPlayDesktop] focus restore failed: %{public}s", e.what()); }
    try { s.api.invoke(s.set_background, nullptr, { &s.saved_background }); }
    catch (const std::exception& e) { os_log_error(OS_LOG_DEFAULT, "[EndPlayDesktop] background restore failed: %{public}s", e.what()); }
    s.active = false;
}

void Runtime::disable(const char* reason)
{
    endSession();
    impl_->error = reason;
    impl_->fatal = true;
}

void Runtime::nativeReset()
{
    if (!ready()) return;
    try { impl_->release(true); }
    catch (const std::exception& e) { os_log_error(OS_LOG_DEFAULT, "[EndPlayDesktop] native reset failed: %{public}s", e.what()); }
}

NSDictionary* Runtime::command(NSDictionary* request)
{
    auto& s = *impl_;
    NSString* op = request[@"op"];
    if ([op isEqual:@"status"] || [op isEqual:@"ping"]) return status();
    if ([op isEqual:@"camera"]) return camera();
    if (!ready()) return Error(s.error);
    try {
        if ([op isEqual:@"begin"]) { s.begin(); return status(); }
        if ([op isEqual:@"end"]) { endSession(); return status(); }
        if (!s.active) return Error("begin an automation session before sending input");
        if ([op isEqual:@"release"]) s.release();
        else if ([op isEqual:@"key"]) s.key(Integer(request, @"vk", 0, 255), Boolean(request, @"down"));
        else if ([op isEqual:@"move"]) {
            const float x = static_cast<float>(Number(request, @"x", 0, s.width - 1));
            const float y = static_cast<float>(Number(request, @"y", 0, s.height - 1));
            s.position(x, y, Boolean(request, @"delta"));
        } else if ([op isEqual:@"button"]) s.button(Integer(request, @"button", 0, 4), Boolean(request, @"down"));
        else if ([op isEqual:@"relative"] || [op isEqual:@"scroll"]) {
            const float dx = static_cast<float>(Number(request, @"dx", -32768, 32768));
            const float dy = static_cast<float>(Number(request, @"dy", -32768, 32768));
            if ([op isEqual:@"relative"]) { s.mouse.dx = dx; s.mouse.dy = -dy; }
            else { s.mouse.scroll_x = dx; s.mouse.scroll_y = dy; }
            s.queueMouse(true);
        } else return Error("unknown operation");
        return status();
    } catch (const std::invalid_argument& exception) { return Error(exception.what()); }
    catch (const std::exception& exception) { endSession(); return Error(exception.what()); }
}

void Runtime::nativeKey(int vk, bool down)
{
    if (!ready() || !impl_->native_focus()) return;
    try { impl_->key(vk, down, true); ++impl_->native_key_events; } catch (const std::exception& e) { os_log_error(OS_LOG_DEFAULT, "[EndPlayDesktop] native key failed: %{public}s", e.what()); }
}
void Runtime::nativeButton(int button, bool down)
{
    if (!ready() || !impl_->native_focus()) return;
    try { impl_->button(button, down, true); ++impl_->native_button_events; } catch (const std::exception& e) { os_log_error(OS_LOG_DEFAULT, "[EndPlayDesktop] native button failed: %{public}s", e.what()); }
}
void Runtime::nativePosition(float x, float y, bool delta)
{
    if (!ready() || !impl_->native_focus()) return;
    try { impl_->position(x, y, delta, true); } catch (const std::exception& e) { os_log_error(OS_LOG_DEFAULT, "[EndPlayDesktop] native pointer failed: %{public}s", e.what()); }
}
void Runtime::nativeDelta(float dx, float dy)
{
    if (!ready() || !impl_->native_focus()) return;
    try { impl_->mouse.dx = dx; impl_->mouse.dy = dy; impl_->queueMouse(); ++impl_->native_delta_events; }
    catch (const std::exception& e) { os_log_error(OS_LOG_DEFAULT, "[EndPlayDesktop] native delta failed: %{public}s", e.what()); }
}
void Runtime::nativeScroll(float dx, float dy)
{
    if (!ready() || !impl_->native_focus()) return;
    try { impl_->mouse.scroll_x = dx; impl_->mouse.scroll_y = dy; impl_->queueMouse(); }
    catch (const std::exception& e) { os_log_error(OS_LOG_DEFAULT, "[EndPlayDesktop] native scroll failed: %{public}s", e.what()); }
}

} // namespace endplaydesktop
