// Adapt only PlayCover controllers tagged maa.endplaydesktop to MaaFramework's
// public CustomController API. No MXU internals or C++ framework ABI are used.
#import <Foundation/Foundation.h>
#include "MaaABI.h"
#include <arpa/inet.h>
#include <dlfcn.h>
#include <signal.h>
#include <spawn.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>
#include <chrono>
#include <cstring>
#include <map>
#include <memory>
#include <mutex>
#include <thread>
#include <string_view>
#include <vector>

extern char** environ;
namespace {
constexpr size_t MaxHeader = 64 * 1024;
constexpr size_t MaxImage = 32 * 1024 * 1024;
struct API {
    MaaController* (*playcover)(const char*, const char*) = nullptr;
    MaaController* (*custom)(MaaCustomControllerCallbacks*, void*) = nullptr;
    void (*destroy)(MaaController*) = nullptr;
    MaaBool (*stringSet)(MaaStringBuffer*, const char*) = nullptr;
    MaaBool (*imageSet)(MaaImageBuffer*, const void*, MaaSize) = nullptr;
};
std::mutex registryMutex;
API api;

struct Driver {
    API framework;
    std::string address;
    std::mutex mutex;
    int wire = -1;
    pid_t child = -1;

    explicit Driver(API functions, const char* endpoint) : framework(functions), address(endpoint) {}
    ~Driver() { close(); }
    void close() {
        if (wire >= 0) { shutdown(wire, SHUT_RDWR); ::close(wire); wire = -1; }
        if (child <= 0) return;
        auto end = std::chrono::steady_clock::now() + std::chrono::seconds(3);
        while (std::chrono::steady_clock::now() < end) {
            int status;
            pid_t result = waitpid(child, &status, WNOHANG);
            if (result == child || (result < 0 && errno == ECHILD)) { child = -1; return; }
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
        kill(child, SIGKILL);
        while (waitpid(child, nullptr, 0) < 0 && errno == EINTR) {}
        child = -1;
    }
    bool start() {
        const char* configPath = getenv("ENDPLAYDESKTOP_CONFIG");
        if (!configPath) return false;
        NSData* data = [NSData dataWithContentsOfFile:[NSString stringWithUTF8String:configPath]];
        NSDictionary* config = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
        if (![config isKindOfClass:NSDictionary.class]) return false;
        NSString* python = config[@"python"];
        NSString* project = config[@"project_dir"];
        if (![python isKindOfClass:NSString.class] || !python.isAbsolutePath ||
            ![project isKindOfClass:NSString.class] || !project.isAbsolutePath ||
            access(python.fileSystemRepresentation, X_OK)) return false;
        int sockets[2];
        if (socketpair(AF_UNIX, SOCK_STREAM, 0, sockets)) return false;
        wire = sockets[0];
        int yes = 1;
        setsockopt(wire, SOL_SOCKET, SO_NOSIGPIPE, &yes, sizeof(yes));
        timeval receive{20, 0}, send{3, 0};
        setsockopt(wire, SOL_SOCKET, SO_RCVTIMEO, &receive, sizeof(receive));
        setsockopt(wire, SOL_SOCKET, SO_SNDTIMEO, &send, sizeof(send));
        posix_spawn_file_actions_t actions;
        posix_spawn_file_actions_init(&actions);
        posix_spawn_file_actions_adddup2(&actions, sockets[1], STDIN_FILENO);
        posix_spawn_file_actions_adddup2(&actions, sockets[1], STDOUT_FILENO);
        posix_spawn_file_actions_addclose(&actions, sockets[0]);
        posix_spawn_file_actions_addclose(&actions, sockets[1]);
        if (@available(macOS 26.0, *)) {
            posix_spawn_file_actions_addchdir(&actions, project.fileSystemRepresentation);
        } else {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
            posix_spawn_file_actions_addchdir_np(&actions, project.fileSystemRepresentation);
#pragma clang diagnostic pop
        }
        std::vector<std::string> storage;
        for (char** entry = environ; *entry; ++entry) {
            std::string_view value(*entry);
            if (!value.starts_with("DYLD_INSERT_LIBRARIES=") && !value.starts_with("_PYI") &&
                !value.starts_with("PYINSTALLER_RESET_ENVIRONMENT=") && !value.starts_with("PYTHONDONTWRITEBYTECODE=") &&
                !value.starts_with("ENDPLAYDESKTOP_")) storage.emplace_back(*entry);
        }
        storage.emplace_back("PYINSTALLER_RESET_ENVIRONMENT=1");
        storage.emplace_back("PYTHONDONTWRITEBYTECODE=1");
        std::vector<char*> env;
        for (auto& value : storage) env.push_back(value.data());
        env.push_back(nullptr);
        const char* values[] = {python.fileSystemRepresentation, "-m", "tools.EndPlayDesktop",
                               "--maatools-address", address.c_str(), "sidecar", nullptr};
        posix_spawnattr_t attributes;
        posix_spawnattr_init(&attributes);
        posix_spawnattr_setflags(&attributes, POSIX_SPAWN_CLOEXEC_DEFAULT);
        int result = posix_spawn(&child, values[0], &actions, &attributes, const_cast<char**>(values), env.data());
        posix_spawnattr_destroy(&attributes);
        posix_spawn_file_actions_destroy(&actions);
        ::close(sockets[1]);
        if (result) { child = -1; close(); return false; }
        return true;
    }
    bool transfer(void* bytes, size_t size, bool sending) {
        auto* cursor = static_cast<char*>(bytes);
        while (size) {
            ssize_t count = sending ? ::send(wire, cursor, size, 0) : recv(wire, cursor, size, 0);
            if (count < 0 && errno == EINTR) continue;
            if (count <= 0) return false;
            cursor += count; size -= count;
        }
        return true;
    }
    bool request(const char* operation, std::initializer_list<int32_t> values, std::vector<uint8_t>* image = nullptr) {
        std::lock_guard lock(mutex);
        @autoreleasepool {
            if (!strcmp(operation, "connect") && wire < 0 && !start()) return false;
            if (wire < 0) return false;
            NSMutableArray* args = [NSMutableArray arrayWithCapacity:values.size()];
            for (int32_t value : values) [args addObject:@(value)];
            NSData* body = [NSJSONSerialization dataWithJSONObject:@{@"op": @(operation), @"args": args}
                                                          options:0 error:nil];
            uint32_t size = htonl(static_cast<uint32_t>(body.length));
            bool valid = transfer(&size, 4, true) && transfer(const_cast<void*>(body.bytes), body.length, true) &&
                         transfer(&size, 4, false);
            size = ntohl(size);
            if (!valid || size == 0 || size > MaxHeader) { close(); return false; }
            NSMutableData* header = [NSMutableData dataWithLength:size];
            if (!transfer(header.mutableBytes, size, false)) { close(); return false; }
            NSDictionary* reply = [NSJSONSerialization JSONObjectWithData:header options:0 error:nil];
            if (![reply isKindOfClass:NSDictionary.class] || ![reply[@"ok"] isEqual:@YES] ||
                ![reply[@"payload_size"] isKindOfClass:NSNumber.class]) { close(); return false; }
            uint64_t length = [reply[@"payload_size"] unsignedLongLongValue];
            if (length > MaxImage || (!image && length)) { close(); return false; }
            if (image) {
                image->resize(length);
                if (length && !transfer(image->data(), length, false)) { close(); return false; }
            }
            return [reply[@"result"] isEqual:@YES];
        }
    }
};
std::map<MaaController*, std::unique_ptr<Driver>> drivers;
Driver& driver(void* data) { return *static_cast<Driver*>(data); }
MaaBool connect(void* data) { return driver(data).request("connect", {}); }
MaaBool connected(void* data) { return driver(data).request("connected", {}); }
MaaBool uuid(void* data, MaaStringBuffer* buffer) { return driver(data).framework.stringSet(buffer, "maa.endplaydesktop"); }
MaaControllerFeature features(void*) { return 3; } // mouse and keyboard down/up
MaaBool unsupportedApp(const char*, void*) { return false; }
MaaBool stop(const char* intent, void* data) {
    return intent && !strcmp(intent, "com.hypergryph.endfield") && driver(data).request("stop_app", {});
}
MaaBool capture(void* data, MaaImageBuffer* buffer) {
    std::vector<uint8_t> image;
    return driver(data).request("screencap", {}, &image) && !image.empty() &&
           driver(data).framework.imageSet(buffer, image.data(), image.size());
}
MaaBool touchDown(int32_t c, int32_t x, int32_t y, int32_t p, void* data) {
    return driver(data).request("touch_down", {c, x, y, p});
}
MaaBool touchMove(int32_t c, int32_t x, int32_t y, int32_t p, void* data) {
    return driver(data).request("touch_move", {c, x, y, p});
}
MaaBool touchUp(int32_t c, void* data) { return driver(data).request("touch_up", {c}); }
MaaBool keyDown(int32_t k, void* data) { return driver(data).request("key_down", {k}); }
MaaBool keyUp(int32_t k, void* data) { return driver(data).request("key_up", {k}); }
MaaBool scroll(int32_t x, int32_t y, void* data) { return driver(data).request("scroll", {x, y}); }
MaaBool relative(int32_t x, int32_t y, void* data) { return driver(data).request("relative_move", {x, y}); }
MaaBool click(int32_t x, int32_t y, void* data) { return touchDown(0, x, y, 0, data) && touchUp(0, data); }
MaaBool clickKey(int32_t k, void* data) { return keyDown(k, data) && keyUp(k, data); }
MaaBool swipe(int32_t, int32_t, int32_t, int32_t, int32_t, void*) { return false; }
MaaBool text(const char*, void*) { return false; }
MaaBool shell(const char*, int64_t, void*, MaaStringBuffer*) { return false; }
MaaBool inactive(void* data) { return driver(data).request("inactive", {}); }
MaaBool info(void* data, MaaStringBuffer* buffer) {
    return driver(data).framework.stringSet(buffer, "{\"backend\":\"EndPlayDesktop\",\"layout\":\"desktop\",\"keycode\":\"win32_vk\"}");
}
MaaCustomControllerCallbacks callbacks{connect, connected, uuid, features, unsupportedApp, stop, capture,
    click, swipe, touchDown, touchMove, touchUp, clickKey, text, keyDown, keyUp, scroll, relative, shell, inactive, info};

MaaController* create(const char* address, const char* controllerUuid) {
    API functions;
    { std::lock_guard lock(registryMutex); functions = api; }
    if (!controllerUuid || strcmp(controllerUuid, "maa.endplaydesktop")) return functions.playcover(address, controllerUuid);
    if (!address || !functions.custom || !functions.stringSet || !functions.imageSet) return nullptr;
    auto instance = std::make_unique<Driver>(functions, address);
    MaaController* controller = functions.custom(&callbacks, instance.get());
    if (controller) { std::lock_guard lock(registryMutex); drivers.emplace(controller, std::move(instance)); }
    return controller;
}
void destroy(MaaController* controller) {
    API functions;
    { std::lock_guard lock(registryMutex); functions = api; }
    functions.destroy(controller);
    std::unique_ptr<Driver> owned;
    {
        std::lock_guard lock(registryMutex);
        auto found = drivers.find(controller);
        if (found != drivers.end()) { owned = std::move(found->second); drivers.erase(found); }
    }
}
} // namespace

__attribute__((constructor)) static void adapterLoaded() {
    setenv("ENDPLAYDESKTOP_ADAPTER_LOADED", "1", 1);
}

// MXU uses libloading/dlsym, so intercept this public dynamic-loader boundary
// rather than any version-specific MXU function or native controller vtable.
static void* adapterDlsym(void* handle, const char* name) {
    void* original = dlsym(handle, name); // dyld excludes bindings within this image
    if (!original || (strcmp(name, "MaaPlayCoverControllerCreate") && strcmp(name, "MaaControllerDestroy"))) return original;
    Dl_info location{};
    if (!dladdr(original, &location) || !location.dli_fname ||
        strcmp(strrchr(location.dli_fname, '/') ? strrchr(location.dli_fname, '/') + 1 : location.dli_fname,
               "libMaaFramework.dylib")) return original;
    std::lock_guard lock(registryMutex);
    if (!strcmp(name, "MaaControllerDestroy")) {
        api.destroy = reinterpret_cast<decltype(api.destroy)>(original);
        return reinterpret_cast<void*>(destroy);
    }
    auto version = reinterpret_cast<const char* (*)()>(dlsym(handle, "MaaVersion"));
    const char* current = version ? version() : "";
    if (*current == 'v') ++current;
    api.playcover = reinterpret_cast<decltype(api.playcover)>(original);
    api.custom = (!strncmp(current, "5.", 2) || !strncmp(current, "6.", 2))
        ? reinterpret_cast<decltype(api.custom)>(dlsym(handle, "MaaCustomControllerCreate")) : nullptr;
    api.stringSet = reinterpret_cast<decltype(api.stringSet)>(dlsym(handle, "MaaStringBufferSet"));
    api.imageSet = reinterpret_cast<decltype(api.imageSet)>(dlsym(handle, "MaaImageBufferSetEncoded"));
    return reinterpret_cast<void*>(create);
}
__attribute__((used)) static const struct { const void* replacement; const void* original; } interpose
    __attribute__((section("__DATA,__interpose"))) = {
        reinterpret_cast<const void*>(adapterDlsym), reinterpret_cast<const void*>(dlsym)};
