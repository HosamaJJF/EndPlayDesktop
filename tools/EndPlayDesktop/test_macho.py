from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from .macho import ADAPTER_LOAD_PATH, add_adapter_dependency, has_adapter_dependency
from .patch import executable_identity


def executable(code: bytes = b"upstream code", *, padding: int = 512) -> bytes:
    commands_size = 24 + 72 + 80
    section_offset = 32 + commands_size + padding
    header = struct.pack("<IIIIIIII", 0xFEEDFACF, 0x100000C, 0, 2, 2, commands_size, 0, 0)
    uuid = struct.pack("<II", 0x1B, 24) + bytes(range(16))
    segment = struct.pack("<II16sQQQQIIII", 0x19, 152, b"__TEXT", 0x100000000,
                          section_offset + len(code), 0, section_offset + len(code), 7, 5, 1, 0)
    section = struct.pack("<16s16sQQIIIIIIII", b"__text", b"__TEXT", 0x100000000 + section_offset,
                          len(code), section_offset, 2, 0, 0, 0, 0, 0, 0)
    return header + uuid + segment + section + bytes(padding) + code


class MachOTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "MaaEnd"

    def test_dependency_uses_padding_preserving_uuid_code_offsets_and_other_commands(self):
        original = executable()
        self.path.write_bytes(original)
        identity = executable_identity(self.path)
        self.assertFalse(has_adapter_dependency(self.path))
        self.assertTrue(add_adapter_dependency(self.path))
        updated = self.path.read_bytes()
        self.assertEqual(len(updated), len(original))
        self.assertEqual(updated[32:208], original[32:208])
        self.assertEqual(updated[720:], original[720:])
        self.assertEqual(executable_identity(self.path), identity)
        self.assertTrue(has_adapter_dependency(self.path))
        self.assertIn(ADAPTER_LOAD_PATH.encode(), updated)
        self.assertFalse(add_adapter_dependency(self.path))
        self.assertEqual(self.path.read_bytes(), updated)

    def test_insufficient_or_occupied_padding_fails_without_writing(self):
        for original in (executable(padding=0), executable(padding=16),
                         executable()[:208] + b"occupied" + executable()[216:]):
            with self.subTest(size=len(original)):
                self.path.write_bytes(original)
                with self.assertRaisesRegex(ValueError, "空间不足"):
                    add_adapter_dependency(self.path)
                self.assertEqual(self.path.read_bytes(), original)

    def test_invalid_headers_commands_and_section_offsets_fail_without_writing(self):
        variants = [b"not Mach-O", executable()[:80]]
        for offset, value in ((4, 0x1000007), (12, 6), (16, 1000), (20, 9),
                              (36, 0), (56 + 64, 1000), (128 + 48, 40)):
            data = bytearray(executable())
            struct.pack_into("<I", data, offset, value)
            variants.append(bytes(data))
        for original in variants:
            with self.subTest(header=original[:32]):
                self.path.write_bytes(original)
                with self.assertRaises(ValueError):
                    add_adapter_dependency(self.path)
                self.assertEqual(self.path.read_bytes(), original)
