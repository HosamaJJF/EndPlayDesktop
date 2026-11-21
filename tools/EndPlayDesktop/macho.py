"""Add a dylib dependency using existing arm64 Mach-O header padding only."""
from __future__ import annotations

import struct
from pathlib import Path

ADAPTER_LOAD_PATH = "@executable_path/../Resources/EndPlayDesktop/libEndPlayDesktopController.dylib"
LC_LOAD_DYLIB = 0xC


def _layout(data: bytes) -> tuple[list[tuple[int, int, int]], int, int]:
    if len(data) < 32 or struct.unpack_from("<III", data) != (0xFEEDFACF, 0x100000C, 0):
        raise ValueError("Expected a thin arm64 Mach-O executable")
    filetype, count, size = struct.unpack_from("<III", data, 12)
    end = 32 + size
    if filetype != 2 or end > len(data) or count > size // 8:
        raise ValueError("Invalid Mach-O executable header")
    commands = []
    payload = len(data)
    offset = 32
    for _ in range(count):
        if offset + 8 > end:
            raise ValueError("Truncated Mach-O load command")
        command, length = struct.unpack_from("<II", data, offset)
        if length < 8 or length % 8 or offset + length > end:
            raise ValueError("Invalid Mach-O load command")
        commands.append((command, offset, length))
        if command == 0x19:  # LC_SEGMENT_64
            if length < 72:
                raise ValueError("Truncated Mach-O segment")
            file_offset, file_size = struct.unpack_from("<QQ", data, offset + 40)
            sections = struct.unpack_from("<I", data, offset + 64)[0]
            if 72 + sections * 80 > length or file_offset + file_size > len(data):
                raise ValueError("Invalid Mach-O segment extent")
            if file_offset and file_size:
                payload = min(payload, file_offset)
            for section in range(sections):
                start = offset + 72 + section * 80
                section_size, section_offset = struct.unpack_from("<QI", data, start + 40)
                kind = struct.unpack_from("<I", data, start + 64)[0] & 0xFF
                if section_size and kind not in (1, 0xC, 0x12):  # zero-fill sections have no file data
                    if section_offset < end or section_offset + section_size > len(data):
                        raise ValueError("Invalid Mach-O section extent")
                    payload = min(payload, section_offset)
        offset += length
    if offset != end or not any(command == 0x19 for command, _, _ in commands):
        raise ValueError("Invalid Mach-O load command table")
    return commands, end, payload


def has_adapter_dependency(path: Path) -> bool:
    data = path.read_bytes()
    commands, _, _ = _layout(data)
    for command, offset, length in commands:
        if command == LC_LOAD_DYLIB:
            if length < 24:
                raise ValueError("Truncated Mach-O dylib command")
            name = struct.unpack_from("<I", data, offset + 8)[0]
            if name < 24 or name >= length:
                raise ValueError("Invalid Mach-O dylib name")
            if data[offset + name:offset + length].split(b"\0", 1)[0] == ADAPTER_LOAD_PATH.encode():
                return True
    return False


def add_adapter_dependency(path: Path) -> bool:
    """Keep all sections, offsets and the build UUID unchanged; sign afterwards."""
    data = path.read_bytes()
    commands, end, payload = _layout(data)
    if has_adapter_dependency(path):
        return False
    name = ADAPTER_LOAD_PATH.encode() + b"\0"
    length = (24 + len(name) + 7) & ~7
    if end + length > payload or any(data[end:end + length]):
        raise ValueError("MXU 的 Mach-O 头部空间不足，无法安全加载适配层；请更新补丁工具。")
    command = struct.pack("<IIIIII", LC_LOAD_DYLIB, length, 24, 0, 0x10000, 0x10000) + name
    updated = bytearray(data)
    updated[end:end + length] = command.ljust(length, b"\0")
    struct.pack_into("<II", updated, 16, len(commands) + 1, end - 32 + length)
    path.write_bytes(updated)
    return True
