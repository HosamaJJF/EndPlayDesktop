cmake_minimum_required(VERSION 3.24)
project(EndPlayDesktop VERSION 0.0.2 LANGUAGES CXX OBJCXX)

if(NOT APPLE)
    message(FATAL_ERROR "EndPlayDesktop requires macOS and the Xcode SDK")
endif()
execute_process(COMMAND xcrun --sdk macosx --show-sdk-path
    OUTPUT_VARIABLE EPD_SDK OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)

function(configure_catalyst target)
target_compile_features(${target} PRIVATE cxx_std_20)
target_compile_options(${target} PRIVATE
    -target arm64-apple-ios15.0-macabi -isysroot "${EPD_SDK}"
    -isystem "${EPD_SDK}/System/iOSSupport/usr/include"
    -iframework "${EPD_SDK}/System/iOSSupport/System/Library/Frameworks"
    -fobjc-arc -Wall -Wextra -Werror -fvisibility=hidden)
target_link_options(${target} PRIVATE
    -target arm64-apple-ios15.0-macabi -isysroot "${EPD_SDK}"
    -iframework "${EPD_SDK}/System/iOSSupport/System/Library/Frameworks"
    "SHELL:-framework Foundation" "SHELL:-framework UIKit"
    "SHELL:-framework GameController" "SHELL:-framework QuartzCore" "SHELL:-framework CoreGraphics")
set_target_properties(${target} PROPERTIES
    OSX_ARCHITECTURES arm64 INSTALL_NAME_DIR "@rpath")
endfunction()

add_library(EndPlayDesktop SHARED
    src/InputState.cpp src/NativeCode.cpp src/Runtime.mm src/Server.mm src/NativeInput.mm src/HostPointer.mm src/Plugin.mm)
configure_catalyst(EndPlayDesktop)
add_custom_command(TARGET EndPlayDesktop POST_BUILD
    COMMAND codesign --force --sign - "$<TARGET_FILE:EndPlayDesktop>"
    VERBATIM)

include(CTest)
if(BUILD_TESTING)
    add_executable(frame_delta_test tests/frame_delta_test.cpp)
    target_include_directories(frame_delta_test PRIVATE src)
    target_compile_features(frame_delta_test PRIVATE cxx_std_20)
    target_compile_options(frame_delta_test PRIVATE -Wall -Wextra -Werror)
    add_test(NAME frame_delta COMMAND frame_delta_test)

    add_executable(scroll_state_test tests/scroll_state_test.cpp)
    target_include_directories(scroll_state_test PRIVATE src)
    target_compile_features(scroll_state_test PRIVATE cxx_std_20)
    target_compile_options(scroll_state_test PRIVATE -Wall -Wextra -Werror)
    add_test(NAME scroll_state COMMAND scroll_state_test)

    add_executable(input_state_test tests/input_state_test.cpp src/InputState.cpp)
    target_include_directories(input_state_test PRIVATE src)
    target_compile_features(input_state_test PRIVATE cxx_std_20)
    target_compile_options(input_state_test PRIVATE -Wall -Wextra -Werror)
    add_test(NAME input_state COMMAND input_state_test)

    add_executable(native_code_test tests/native_code_test.cpp src/NativeCode.cpp)
    target_include_directories(native_code_test PRIVATE src)
    target_compile_features(native_code_test PRIVATE cxx_std_20)
    target_compile_options(native_code_test PRIVATE -Wall -Wextra -Werror)
    add_test(NAME native_code COMMAND native_code_test)

    add_library(mock_unity SHARED tests/mock_unity.mm)
    configure_catalyst(mock_unity)
    set_target_properties(mock_unity PROPERTIES PREFIX "" SUFFIX "" OUTPUT_NAME UnityFramework
        INSTALL_NAME_DIR "@rpath/UnityFramework.framework" BUILD_WITH_INSTALL_NAME_DIR TRUE
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/fixtures/UnityFramework.framework")
    add_executable(runtime_test tests/runtime_test.mm src/Runtime.mm src/InputState.cpp src/NativeCode.cpp)
    configure_catalyst(runtime_test)
    target_include_directories(runtime_test PRIVATE src)
    target_link_libraries(runtime_test PRIVATE mock_unity)
    set_target_properties(runtime_test PROPERTIES BUILD_RPATH "${CMAKE_BINARY_DIR}/fixtures")
    add_test(NAME managed_runtime COMMAND runtime_test)

    add_executable(cursor_bridge_test tests/cursor_bridge_test.mm src/Runtime.mm src/InputState.cpp src/NativeCode.cpp)
    configure_catalyst(cursor_bridge_test)
    target_include_directories(cursor_bridge_test PRIVATE src)
    target_link_libraries(cursor_bridge_test PRIVATE mock_unity)
    set_target_properties(cursor_bridge_test PROPERTIES BUILD_RPATH "${CMAKE_BINARY_DIR}/fixtures")
    add_test(NAME cursor_bridge COMMAND cursor_bridge_test)

    add_executable(native_input_test tests/native_input_test.mm src/NativeInput.mm src/Runtime.mm src/InputState.cpp src/NativeCode.cpp)
    configure_catalyst(native_input_test)
    target_include_directories(native_input_test PRIVATE src)
    target_link_libraries(native_input_test PRIVATE mock_unity)
    set_target_properties(native_input_test PROPERTIES BUILD_RPATH "${CMAKE_BINARY_DIR}/fixtures")
    add_test(NAME native_input COMMAND native_input_test)

    add_executable(host_pointer_test tests/host_pointer_test.mm src/HostPointer.mm src/Runtime.mm src/InputState.cpp src/NativeCode.cpp)
    configure_catalyst(host_pointer_test)
    target_include_directories(host_pointer_test PRIVATE src)
    target_link_libraries(host_pointer_test PRIVATE mock_unity)
    set_target_properties(host_pointer_test PROPERTIES BUILD_RPATH "${CMAKE_BINARY_DIR}/fixtures")
    add_test(NAME host_pointer COMMAND host_pointer_test)

    add_executable(server_test tests/server_test.mm src/Server.mm src/Runtime.mm src/InputState.cpp src/NativeCode.cpp)
    configure_catalyst(server_test)
    target_include_directories(server_test PRIVATE src)
    target_link_libraries(server_test PRIVATE mock_unity)
    set_target_properties(server_test PROPERTIES BUILD_RPATH "${CMAKE_BINARY_DIR}/fixtures")
    add_test(NAME server_heartbeat COMMAND server_test)
    set_tests_properties(server_heartbeat PROPERTIES TIMEOUT 10)

endif()
