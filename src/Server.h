#pragma once

#import <Foundation/Foundation.h>

namespace endplaydesktop::transport
{
// 接管已 accept 的 socket，验证客户端后执行协议；函数返回时关闭 socket。
void HandleClient(int fd, NSString* token);
} // namespace endplaydesktop::transport
