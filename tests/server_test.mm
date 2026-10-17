#include "Runtime.h"
#include "Server.h"

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>

using namespace endplaydesktop;
extern "C" void EPDTestReset();

static void Require(bool value, const char* message)
{
    if (!value) { std::cerr << message << '\n'; std::exit(1); }
}

static NSDictionary* Exchange(int fd, NSDictionary* request)
{
    NSData* data = [NSJSONSerialization dataWithJSONObject:request options:0 error:nil];
    uint32_t length = htonl(static_cast<uint32_t>(data.length));
    Require(send(fd, &length, 4, 0) == 4 && send(fd, data.bytes, data.length, 0) == static_cast<ssize_t>(data.length), "request write failed");
    Require(recv(fd, &length, 4, MSG_WAITALL) == 4, "response header failed");
    length = ntohl(length);
    Require(length > 0 && length < 65536, "response size invalid");
    NSMutableData* body = [NSMutableData dataWithLength:length];
    Require(recv(fd, body.mutableBytes, length, MSG_WAITALL) == length, "response body failed");
    return [NSJSONSerialization JSONObjectWithData:body options:0 error:nil];
}

int main()
{
    @autoreleasepool {
        EPDTestReset();
        GetRuntime().tick();
        Require(GetRuntime().ready(), "mock runtime must initialize");
        int pair[2];
        Require(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0, "socketpair failed");
        const timeval timeout { 3, 0 };
        setsockopt(pair[0], SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
        std::atomic<bool> authenticated { false }, block_main { false };
        dispatch_semaphore_t replied = dispatch_semaphore_create(0);
        std::thread server([&] { @autoreleasepool { transport::HandleClient(pair[1], @"test-token"); } });
        std::thread client([&] {
            @autoreleasepool {
                NSDictionary* hello = Exchange(pair[0], @{ @"op": @"hello", @"protocol": @1, @"token": @"test-token" });
                Require([hello[@"ready"] boolValue], "authentication must read runtime status");
                authenticated.store(true);
                while (!block_main.load()) std::this_thread::sleep_for(std::chrono::milliseconds(1));
                NSDictionary* ping = Exchange(pair[0], @{ @"op": @"ping" });
                Require([ping[@"ok"] boolValue], "heartbeat must succeed while main thread is blocked");
                dispatch_semaphore_signal(replied);
                close(pair[0]);
            }
        });
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
        while (!authenticated.load() && std::chrono::steady_clock::now() < deadline) {
            [NSRunLoop.mainRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
        }
        Require(authenticated.load(), "authentication must complete");
        block_main.store(true);
        // 故意阻塞主队列；若心跳仍派发到主线程，此断言会超时。
        Require(dispatch_semaphore_wait(replied, dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC)) == 0,
                "heartbeat must not depend on a responsive Unity main thread");
        client.join();
        server.join();
        [NSRunLoop.mainRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
        std::cout << "server heartbeat checks passed\n";
    }
}
