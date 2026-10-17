#include "Runtime.h"
#include "Server.h"

#include <array>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <memory>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>

#import <os/log.h>

namespace endplaydesktop
{
namespace
{

constexpr uint32_t kMaxMessage = 64 * 1024;
constexpr int kLeaseSeconds = 3;
std::atomic<bool> session_claimed { false };

class Socket
{
public:
    explicit Socket(int fd) : fd_(fd) {}
    ~Socket() { if (fd_ >= 0) close(fd_); }
    Socket(const Socket&) = delete;
    Socket& operator=(const Socket&) = delete;
    int get() const { return fd_; }
private:
    int fd_;
};

using Deadline = std::chrono::steady_clock::time_point;

bool Transfer(int fd, void* bytes, size_t count, bool writing, Deadline deadline)
{
    char* cursor = static_cast<char*>(bytes);
    while (count) {
        const auto remaining = std::chrono::duration_cast<std::chrono::microseconds>(deadline - std::chrono::steady_clock::now());
        if (remaining.count() <= 0) return false;
        const timeval timeout { static_cast<time_t>(remaining.count() / 1000000),
                                static_cast<suseconds_t>(remaining.count() % 1000000) };
        if (setsockopt(fd, SOL_SOCKET, writing ? SO_SNDTIMEO : SO_RCVTIMEO, &timeout, sizeof(timeout))) return false;
        const ssize_t done = writing ? send(fd, cursor, count, 0) : recv(fd, cursor, count, 0);
        if (done < 0 && errno == EINTR) continue;
        if (done <= 0) return false;
        cursor += done;
        count -= static_cast<size_t>(done);
    }
    return true;
}

NSDictionary* Receive(int fd)
{
    uint32_t length = 0;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(kLeaseSeconds);
    if (!Transfer(fd, &length, sizeof(length), false, deadline)) return nil;
    length = ntohl(length);
    if (!length || length > kMaxMessage) return nil;
    NSMutableData* data = [NSMutableData dataWithLength:length];
    if (!Transfer(fd, data.mutableBytes, data.length, false, deadline)) return nil;
    id result = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
    return [result isKindOfClass:NSDictionary.class] ? result : nil;
}

bool Reply(int fd, NSDictionary* response)
{
    NSData* data = [NSJSONSerialization dataWithJSONObject:response options:0 error:nil];
    if (!data || data.length > kMaxMessage) return false;
    uint32_t length = htonl(static_cast<uint32_t>(data.length));
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(kLeaseSeconds);
    return Transfer(fd, &length, sizeof(length), true, deadline)
           && Transfer(fd, const_cast<void*>(data.bytes), data.length, true, deadline);
}

NSDictionary* MainCommand(NSDictionary* request)
{
    struct Pending
    {
        std::atomic<bool> cancelled { false };
        dispatch_semaphore_t completed = dispatch_semaphore_create(0);
        NSDictionary* response = nil;
    };
    auto pending = std::make_shared<Pending>();
    dispatch_async(dispatch_get_main_queue(), ^{
        if (!pending->cancelled.load()) pending->response = GetRuntime().command(request);
        dispatch_semaphore_signal(pending->completed);
    });
    if (dispatch_semaphore_wait(pending->completed, dispatch_time(DISPATCH_TIME_NOW, 2 * NSEC_PER_SEC))) {
        pending->cancelled.store(true);
        return @{ @"ok": @NO, @"error": @"game main thread did not respond" };
    }
    return pending->response;
}

} // namespace

void transport::HandleClient(int fd, NSString* token)
{
    Socket client(fd);
    const timeval timeout { kLeaseSeconds, 0 };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    const int no_sigpipe = 1;
    setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &no_sigpipe, sizeof(no_sigpipe));

    NSDictionary* hello = Receive(fd);
    if (![hello[@"op"] isEqual:@"hello"] || ![hello[@"protocol"] isEqual:@1] || ![hello[@"token"] isEqual:token]) {
        Reply(fd, @{ @"ok": @NO, @"error": @"authentication or protocol mismatch" });
        return;
    }
    if (session_claimed.exchange(true)) {
        Reply(fd, @{ @"ok": @NO, @"error": @"another client owns the connection" });
        return;
    }
    // 只有经过验证且获得连接所有权的客户端，才能安排输入和释放该会话。
    if (Reply(fd, MainCommand(@{ @"op": @"status" }))) {
        while (NSDictionary* request = Receive(fd)) {
            // 心跳只证明本地服务存活，不能等待正忙于转场的 Unity 主线程。
            // status 与所有输入仍经主队列执行，并保留超时取消。
            NSDictionary* response = [request[@"op"] isEqual:@"ping"] ? @{ @"ok": @YES } : MainCommand(request);
            if (!Reply(fd, response)) break;
            if ([response[@"error"] isEqual:@"game main thread did not respond"]) break;
        }
    }
    // 清理与下一连接的 begin 都在主队列串行执行，防止旧连接释放新连接的按键。
    dispatch_async(dispatch_get_main_queue(), ^{ GetRuntime().endSession(); session_claimed.store(false); });
}

namespace
{

NSString* NewToken()
{
    std::array<uint8_t, 32> bytes;
    arc4random_buf(bytes.data(), bytes.size());
    NSMutableString* token = [NSMutableString stringWithCapacity:64];
    for (uint8_t value : bytes) [token appendFormat:@"%02x", value];
    return token;
}

bool WriteEndpoint(uint16_t port, NSString* token)
{
    NSURL* cache = [NSFileManager.defaultManager URLsForDirectory:NSCachesDirectory inDomains:NSUserDomainMask].firstObject;
    NSURL* directory = [cache URLByAppendingPathComponent:@"EndPlayDesktop" isDirectory:YES];
    NSError* error = nil;
    if (![NSFileManager.defaultManager createDirectoryAtURL:directory withIntermediateDirectories:YES
                                               attributes:@{ NSFilePosixPermissions: @0700 } error:&error]) return false;
    chmod(directory.fileSystemRepresentation, 0700);
    NSURL* file = [directory URLByAppendingPathComponent:@"endpoint.json"];
    NSDictionary* endpoint = @{ @"protocol": @1, @"host": @"127.0.0.1", @"port": @(port),
                               @"pid": @(getpid()), @"bundle_id": NSBundle.mainBundle.bundleIdentifier,
                               @"token": token };
    NSData* data = [NSJSONSerialization dataWithJSONObject:endpoint options:0 error:&error];
    if (!data || ![data writeToURL:file options:NSDataWritingAtomic error:&error]) return false;
    if (chmod(file.fileSystemRepresentation, 0600)) return false;
    os_log_info(OS_LOG_DEFAULT, "[EndPlayDesktop] connection descriptor: %{public}@", file.path);
    return true;
}

} // namespace

void StartServer()
{
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        @autoreleasepool {
            Socket listener(socket(AF_INET, SOCK_STREAM, 0));
            sockaddr_in address {};
            address.sin_len = sizeof(address);
            address.sin_family = AF_INET;
            address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
            if (listener.get() < 0 || bind(listener.get(), reinterpret_cast<sockaddr*>(&address), sizeof(address))
                || listen(listener.get(), 4)) {
                os_log_error(OS_LOG_DEFAULT, "[EndPlayDesktop] cannot start local input server: %s", strerror(errno));
                return;
            }
            socklen_t size = sizeof(address);
            if (getsockname(listener.get(), reinterpret_cast<sockaddr*>(&address), &size)) return;
            NSString* token = NewToken();
            if (!WriteEndpoint(ntohs(address.sin_port), token)) {
                os_log_error(OS_LOG_DEFAULT, "[EndPlayDesktop] cannot write private connection descriptor");
                return;
            }
            for (;;) {
                const int client = accept(listener.get(), nullptr, nullptr);
                if (client < 0) {
                    if (errno == EINTR) continue;
                    os_log_error(OS_LOG_DEFAULT, "[EndPlayDesktop] accept failed: %s", strerror(errno));
                    break;
                }
                dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
                    @autoreleasepool { transport::HandleClient(client, token); }
                });
            }
        }
    });
}

} // namespace endplaydesktop
