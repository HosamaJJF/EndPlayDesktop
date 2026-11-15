// Launch the untouched upstream client with a process-local controller adapter.
#import <Foundation/Foundation.h>
#include <mach-o/dyld.h>
#include <unistd.h>
#include <cstdio>
#include <vector>

int main(int argc, char** argv) {
    @autoreleasepool {
        uint32_t size = 0;
        _NSGetExecutablePath(nullptr, &size);
        std::vector<char> path(size);
        if (_NSGetExecutablePath(path.data(), &size) != 0) return 1;
        NSString* executable = [[NSString stringWithUTF8String:path.data()] stringByResolvingSymlinksInPath];
        NSString* contents = [[executable stringByDeletingLastPathComponent] stringByDeletingLastPathComponent];
        NSString* resources = [contents stringByAppendingPathComponent:@"Resources/EndPlayDesktop"];
        NSString* configPath = [resources stringByAppendingPathComponent:@"runtime.json"];
        NSData* data = [NSData dataWithContentsOfFile:configPath];
        NSDictionary* config = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
        if (![config isKindOfClass:NSDictionary.class]) return 1;
        NSString* name = config[@"upstream_executable"];
        if (![name isKindOfClass:NSString.class] || !name.length ||
            ![name.lastPathComponent isEqualToString:name] || [name isEqualToString:executable.lastPathComponent]) {
            fprintf(stderr, "EndPlayDesktop: invalid upstream executable\n");
            return 1;
        }
        NSString* original = [[contents stringByAppendingPathComponent:@"MacOS"] stringByAppendingPathComponent:name];
        NSString* adapter = [resources stringByAppendingPathComponent:@"libEndPlayDesktopController.dylib"];
        if (access(original.fileSystemRepresentation, X_OK) || access(adapter.fileSystemRepresentation, R_OK)) {
            fprintf(stderr, "EndPlayDesktop: missing upstream client or controller adapter\n");
            return 1;
        }
        // Child Agents/sidecars remove this variable before exec; no global env
        // or launch services settings are changed.
        setenv("DYLD_INSERT_LIBRARIES", adapter.fileSystemRepresentation, 1);
        setenv("ENDPLAYDESKTOP_CONFIG", configPath.fileSystemRepresentation, 1);
        unsetenv("ENDPLAYDESKTOP_ADAPTER_LOADED");
        std::vector<char*> arguments;
        arguments.push_back(const_cast<char*>(original.fileSystemRepresentation));
        for (int i = 1; i < argc; ++i) arguments.push_back(argv[i]);
        arguments.push_back(nullptr);
        execv(original.fileSystemRepresentation, arguments.data());
        perror("EndPlayDesktop: cannot launch upstream client");
        return 1;
    }
}
