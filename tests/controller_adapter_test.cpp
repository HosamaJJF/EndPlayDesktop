#include <dlfcn.h>
#include <cassert>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <CoreFoundation/CoreFoundation.h>
int main(int argc, char** argv) {
    assert(argc == 3 && !strcmp(argv[2], "argument with spaces"));
    assert(!getenv("DYLD_INSERT_LIBRARIES"));
    assert(getenv("ENDPLAYDESKTOP_ADAPTER_LOADED") && !strcmp(getenv("ENDPLAYDESKTOP_ADAPTER_LOADED"), "1"));
    assert(CFEqual(CFBundleGetIdentifier(CFBundleGetMainBundle()), CFSTR("test.endplaydesktop.adapter")));
    void* library = dlopen(argv[1], RTLD_NOW);
    if (!library) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    auto create = reinterpret_cast<void* (*)(const char*, const char*)>(dlsym(library, "MaaPlayCoverControllerCreate"));
    auto destroy = reinterpret_cast<void (*)(void*)>(dlsym(library, "MaaControllerDestroy"));
    auto native = reinterpret_cast<bool (*)(void*)>(dlsym(library, "TestNativeController"));
    auto custom = reinterpret_cast<bool (*)(void*)>(dlsym(library, "TestCustomController"));
    assert(create && destroy && native && custom);
    Dl_info info{};
    assert(dladdr(reinterpret_cast<void*>(create), &info) && strstr(info.dli_fname, "libEndPlayDesktopController.dylib"));
    void* normal = create("127.0.0.1:1717", "maa.playcover");
    assert(normal && native(normal));
    destroy(normal);
    void* controller = create("127.0.0.1:1718", "maa.endplaydesktop");
    assert(controller && custom(controller));
    destroy(controller);
    puts("upstream controller factory and sidecar protocol passed");
    return 0;
}
