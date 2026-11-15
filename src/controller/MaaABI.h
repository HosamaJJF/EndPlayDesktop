// Minimal MaaFramework C ABI, from its LGPL-3.0 public header layouts.
// Keep the callback field order in sync with MaaCustomControllerCallbacks.
#pragma once
#include <cstdint>

using MaaBool = uint8_t;
using MaaSize = uint64_t;
using MaaControllerFeature = uint64_t;
struct MaaController;
struct MaaStringBuffer;
struct MaaImageBuffer;

struct MaaCustomControllerCallbacks {
    MaaBool (*connect)(void*);
    MaaBool (*connected)(void*);
    MaaBool (*request_uuid)(void*, MaaStringBuffer*);
    MaaControllerFeature (*get_features)(void*);
    MaaBool (*start_app)(const char*, void*);
    MaaBool (*stop_app)(const char*, void*);
    MaaBool (*screencap)(void*, MaaImageBuffer*);
    MaaBool (*click)(int32_t, int32_t, void*);
    MaaBool (*swipe)(int32_t, int32_t, int32_t, int32_t, int32_t, void*);
    MaaBool (*touch_down)(int32_t, int32_t, int32_t, int32_t, void*);
    MaaBool (*touch_move)(int32_t, int32_t, int32_t, int32_t, void*);
    MaaBool (*touch_up)(int32_t, void*);
    MaaBool (*click_key)(int32_t, void*);
    MaaBool (*input_text)(const char*, void*);
    MaaBool (*key_down)(int32_t, void*);
    MaaBool (*key_up)(int32_t, void*);
    MaaBool (*scroll)(int32_t, int32_t, void*);
    MaaBool (*relative_move)(int32_t, int32_t, void*);
    MaaBool (*shell)(const char*, int64_t, void*, MaaStringBuffer*);
    MaaBool (*inactive)(void*);
    MaaBool (*get_info)(void*, MaaStringBuffer*);
};
