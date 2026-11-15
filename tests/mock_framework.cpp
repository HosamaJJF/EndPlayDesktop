#include "MaaABI.h"
#include <cstring>
#include <string>
struct MaaController { MaaCustomControllerCallbacks* callbacks; void* data; };
struct MaaStringBuffer { std::string value; };
struct MaaImageBuffer { std::string value; };
extern "C" {
const char* MaaVersion() { return "v5.15.0"; }
MaaController* MaaPlayCoverControllerCreate(const char*, const char*) { return new MaaController{nullptr, nullptr}; }
MaaController* MaaCustomControllerCreate(MaaCustomControllerCallbacks* callbacks, void* data) { return new MaaController{callbacks, data}; }
void MaaControllerDestroy(MaaController* controller) { delete controller; }
MaaBool MaaStringBufferSet(MaaStringBuffer* buffer, const char* value) { buffer->value = value; return true; }
MaaBool MaaImageBufferSetEncoded(MaaImageBuffer* buffer, const void* data, MaaSize size) {
    buffer->value.assign(static_cast<const char*>(data), size);
    return buffer->value == "test image";
}
bool TestNativeController(MaaController* controller) { return !controller->callbacks; }
bool TestCustomController(MaaController* controller) {
    auto* c = controller->callbacks;
    auto* data = controller->data;
    if (!c || c->get_features(data) != 3) return false;
    MaaStringBuffer uuid, info;
    MaaImageBuffer image;
    return c->connect(data) && c->connected(data) && c->request_uuid(data, &uuid) && uuid.value == "maa.endplaydesktop" &&
           c->get_info(data, &info) && info.value.find("win32_vk") != std::string::npos &&
           c->screencap(data, &image) && c->touch_down(1, 100, 200, 0, data) && c->touch_move(1, 110, 210, 0, data) &&
           c->touch_up(1, data) && c->key_down(87, data) && c->key_up(87, data) &&
           c->scroll(0, 120, data) && c->relative_move(25, -10, data) && c->inactive(data) &&
           !c->stop_app("another.game", data) && c->stop_app("com.hypergryph.endfield", data);
}
}
