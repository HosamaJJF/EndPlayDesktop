#include "../src/InputState.h"

#include <cstring>
#include <functional>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

using namespace endplaydesktop;

namespace
{
struct MockClass;
struct Object { MockClass* klass = nullptr; std::vector<uint8_t> data; std::string text; };
struct MockMethod
{
    std::string name;
    std::vector<std::string> types;
    std::function<Object*(Object*, void**)> run;
};
struct MockClass { std::string space, name; std::vector<MockMethod> methods; };
struct Device { uint32_t format; int id; uint32_t size; };
std::vector<std::unique_ptr<MockClass>> classes;
std::vector<std::unique_ptr<Object>> objects;
std::map<uint32_t, Object*> handles;
std::vector<std::vector<uint8_t>> events;
int input_type = 1, platform = 0, focus = 0;
bool background = false, fail_enable = false;
uint32_t next_handle = 1;
MockClass *device_class = nullptr, *settings_class = nullptr;
Object *runtime = nullptr, *settings = nullptr, *manager = nullptr;
MockClass* system_class = nullptr;

Object* NewObject(MockClass* klass = nullptr)
{
    auto object = std::make_unique<Object>();
    object->klass = klass;
    Object* result = object.get();
    objects.push_back(std::move(object));
    return result;
}

template <typename T> Object* Box(T value)
{
    Object* result = NewObject();
    result->data.resize(sizeof(value));
    std::memcpy(result->data.data(), &value, sizeof(value));
    return result;
}

MockClass* AddClass(const char* space, const char* name, std::vector<MockMethod> methods)
{
    auto klass = std::make_unique<MockClass>(MockClass { space, name, std::move(methods) });
    MockClass* result = klass.get();
    classes.push_back(std::move(klass));
    return result;
}
} // namespace

#define EXPORTED extern "C" __attribute__((visibility("default")))

EXPORTED void EPDTestReset()
{
    AddClass("Beyond", "DeviceInfo", {
        { "get_inputType", {}, [](Object*, void**) { return Box(input_type); } },
        { "set_inputType", { "Beyond.DeviceInfo.InputType" }, [](Object*, void** p) { input_type = *static_cast<int*>(p[0]); return nullptr; } },
        { "set_platform", { "UnityEngine.RuntimePlatform" }, [](Object*, void** p) { platform = *static_cast<int*>(p[0]); return nullptr; } },
    });
    AddClass("UnityEngine", "Screen", {
        { "get_width", {}, [](Object*, void**) { return Box(1280); } },
        { "get_height", {}, [](Object*, void**) { return Box(720); } },
    });
    AddClass("UnityEngine", "Application", {
        { "get_runInBackground", {}, [](Object*, void**) { return Box(background); } },
        { "set_runInBackground", { "System.Boolean" }, [](Object*, void** p) { background = *static_cast<bool*>(p[0]); return nullptr; } },
    });
    settings_class = AddClass("UnityEngine.InputSystem", "InputSettings", {
        { "get_backgroundBehavior", {}, [](Object*, void**) { return Box(focus); } },
        { "set_backgroundBehavior", { "UnityEngine.InputSystem.InputSettings.BackgroundBehavior" }, [](Object*, void** p) { focus = *static_cast<int*>(p[0]); return nullptr; } },
    });
    settings = NewObject(settings_class);
    device_class = AddClass("UnityEngine.InputSystem", "InputDevice", {
        { "get_deviceId", {}, [](Object* o, void**) { Device d; std::memcpy(&d, o->data.data(), sizeof(d)); return Box(d.id); } },
        { "get_stateBlock", {}, [](Object* o, void**) { Device d; std::memcpy(&d, o->data.data(), sizeof(d));
            struct Block { uint32_t format, byte_offset, bit_offset, size_bits; };
            return Box(Block { d.format, 0, 0, d.size * 8 }); } },
    });
    system_class = AddClass("UnityEngine.InputSystem", "InputSystem", {
        { "get_settings", {}, [](Object*, void**) { return settings; } },
        { "AddDevice", { "System.String", "System.String", "System.String" }, [](Object*, void** p) {
            const bool keyboard = static_cast<Object*>(p[0])->text == "Keyboard";
            Object* o = Box(Device { keyboard ? FourCC('K','E','Y','S') : FourCC('M','O','U','S'), keyboard ? 7 : 8, keyboard ? 16u : 30u });
            o->klass = device_class; return o; } },
        { "QueueEvent", { "UnityEngine.InputSystem.LowLevel.InputEvent*" }, [](Object*, void** p) {
            // IL2CPP runtime_invoke 对 InputEvent* 直接接收指针，不再间接解引用。
            const auto* bytes = static_cast<uint8_t*>(p[0]);
            InputEventHeader header; std::memcpy(&header, bytes, sizeof(header));
            if (header.type != FourCC('S','T','A','T') || header.time != 12.5) throw std::runtime_error("invalid native event header");
            events.emplace_back(bytes, bytes + header.size); return nullptr; } },
        { "EnableDevice", { "UnityEngine.InputSystem.InputDevice" }, [](Object*, void**) -> Object* {
            if (fail_enable) throw std::runtime_error("simulated EnableDevice failure"); return nullptr; } },
        { "RemoveDevice", { "UnityEngine.InputSystem.InputDevice" }, [](Object*, void**) -> Object* { return nullptr; } },
    });
    auto add = system_class->methods[1].run;
    auto queue = system_class->methods[2].run;
    MockClass* manager_class = AddClass("UnityEngine.InputSystem", "InputManager", {
        { "AddDevice", { "System.String", "System.String", "UnityEngine.InputSystem.Utilities.InternedString" }, add },
        { "QueueEvent", { "UnityEngine.InputSystem.LowLevel.InputEvent*" }, queue },
    });
    manager = NewObject(manager_class);
    MockClass* native_runtime = AddClass("UnityEngine.InputSystem.LowLevel", "NativeInputRuntime", {
        { "get_instance", {}, [](Object*, void**) { return runtime; } },
        { "get_currentTime", {}, [](Object*, void**) { return Box(12.5); } },
    });
    runtime = NewObject(native_runtime);
    AddClass("UnityEngine.InputSystem.LowLevel", "InputState", {
        { "get_updateCount", {}, [](Object*, void**) { return Box(uint32_t(9)); } },
    });
    auto* transform_class = AddClass("UnityEngine", "Transform", {
        { "get_eulerAngles", {}, [](Object*, void**) {
            struct Vector3 { float x, y, z; };
            return Box(Vector3 { 350, 42, 0 }); } },
    });
    auto* transform = NewObject(transform_class);
    auto* camera = NewObject();
    auto* camera_class = AddClass("UnityEngine", "Camera", {
        { "get_main", {}, [camera](Object*, void**) { return camera; } },
        { "get_transform", {}, [transform](Object*, void**) { return transform; } },
        { "get_fieldOfView", {}, [](Object*, void**) { return Box(60.0f); } },
    });
    camera->klass = camera_class;
}

EXPORTED void EPDTestUseManagerOnly()
{
    std::erase_if(system_class->methods, [](const MockMethod& method) { return method.name == "AddDevice" || method.name == "QueueEvent"; });
    std::erase_if(runtime->klass->methods, [](const MockMethod& method) { return method.name == "get_instance"; });
}

EXPORTED int EPDTestPlatform() { return platform; }
EXPORTED int EPDTestFocus() { return focus; }
EXPORTED bool EPDTestBackground() { return background; }
EXPORTED void EPDTestFailEnable(bool fail) { fail_enable = fail; }
EXPORTED bool EPDTestKeyDown(int index)
{
    for (auto i = events.rbegin(); i != events.rend(); ++i) {
        InputEventHeader header; std::memcpy(&header, i->data(), sizeof(header));
        if (header.device == 7) return ((*i)[24 + index / 8] & (1 << (index % 8))) != 0;
    }
    return false;
}
EXPORTED void EPDTestMouse(MouseState* result)
{
    for (auto i = events.rbegin(); i != events.rend(); ++i) {
        InputEventHeader header; std::memcpy(&header, i->data(), sizeof(header));
        if (header.device == 8) { std::memcpy(result, i->data() + 24, sizeof(*result)); return; }
    }
    *result = {};
}

EXPORTED void* il2cpp_domain_get() { return reinterpret_cast<void*>(1); }
EXPORTED const void** il2cpp_domain_get_assemblies(void*, size_t* count) { static const void* assemblies[] = { reinterpret_cast<void*>(1) }; *count = 1; return assemblies; }
EXPORTED const void* il2cpp_assembly_get_image(const void* image) { return image; }
EXPORTED void* il2cpp_class_from_name(const void*, const char* space, const char* name)
{
    for (auto& klass : classes) if (klass->space == space && klass->name == name) return klass.get();
    return nullptr;
}
EXPORTED void* il2cpp_class_get_parent(void*) { return nullptr; }
EXPORTED void* il2cpp_class_get_field_from_name(void* klass, const char* name)
{
    if (klass == system_class && std::strcmp(name, "s_Manager") == 0) return reinterpret_cast<void*>(1);
    if (klass == runtime->klass && std::strcmp(name, "instance") == 0) return reinterpret_cast<void*>(2);
    return nullptr;
}
EXPORTED void il2cpp_field_static_get_value(const void* field, void* output) { *static_cast<Object**>(output) = field == reinterpret_cast<void*>(1) ? manager : runtime; }
EXPORTED const void* il2cpp_class_get_methods(void* klass, void** iterator)
{
    auto& methods = static_cast<MockClass*>(klass)->methods;
    const auto index = reinterpret_cast<uintptr_t>(*iterator);
    if (index >= methods.size()) return nullptr;
    *iterator = reinterpret_cast<void*>(index + 1);
    return &methods[index];
}
EXPORTED const char* il2cpp_method_get_name(const void* method) { return static_cast<const MockMethod*>(method)->name.c_str(); }
EXPORTED uint32_t il2cpp_method_get_param_count(const void* method) { return static_cast<uint32_t>(static_cast<const MockMethod*>(method)->types.size()); }
EXPORTED const void* il2cpp_method_get_param(const void* method, uint32_t index) { return &static_cast<const MockMethod*>(method)->types.at(index); }
EXPORTED char* il2cpp_type_get_name(const void* type) { return strdup(static_cast<const std::string*>(type)->c_str()); }
EXPORTED void* il2cpp_runtime_invoke(const void* method, void* object, void** args, void** exception)
{
    try { return static_cast<const MockMethod*>(method)->run(static_cast<Object*>(object), args); }
    catch (const std::exception& e) { Object* error = NewObject(); error->text = e.what(); *exception = error; return nullptr; }
}
EXPORTED void* il2cpp_object_unbox(void* object) { return static_cast<Object*>(object)->data.data(); }
EXPORTED void* il2cpp_object_get_class(void* object) { return static_cast<Object*>(object)->klass; }
EXPORTED void* il2cpp_string_new(const char* text) { Object* result = NewObject(); result->text = text; return result; }
EXPORTED uint32_t il2cpp_gchandle_new(void* object, bool) { uint32_t id = next_handle++; handles[id] = static_cast<Object*>(object); return id; }
EXPORTED void* il2cpp_gchandle_get_target(uint32_t id) { return handles.at(id); }
EXPORTED void il2cpp_gchandle_free(uint32_t id) { handles.erase(id); }
EXPORTED void il2cpp_free(void* memory) { std::free(memory); }
EXPORTED void* il2cpp_thread_attach(void* domain) { return domain; }
EXPORTED void il2cpp_format_exception(void* object, char* text, int size) { strlcpy(text, static_cast<Object*>(object)->text.c_str(), static_cast<size_t>(size)); }
