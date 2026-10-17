from __future__ import annotations

import plistlib
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from .build_patch import prepare_mxu
from .patch import (CONTROLLER, RECEIPT, app_info, apply_patch, digest, load_payload,
                    resource_changes, restore, write_json)


class AppPatchTests(unittest.TestCase):
    def setUp(self) -> None:
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.app = self.root / "MaaEnd.app"
        self.directory = self.app / "Contents/MacOS"
        self.directory.mkdir(parents=True)
        self.info = {"CFBundleExecutable": "MaaEnd", "CFBundleIdentifier": "com.maaend.app",
                     "CFBundleName": "MaaEnd", "CFBundleShortVersionString": "v2.33.0"}
        (self.app / "Contents/Info.plist").write_bytes(plistlib.dumps(self.info))
        self.interface = {
            "name": "MaaEnd", "version": "v2.33.0", "github": "upstream", "telemetry": {"retain": True},
            "controller": [{"name": "Win32-Front", "type": "Win32"},
                           {"name": "AnotherWindows", "type": "Win32"},
                           {"name": "PlayCover", "type": "PlayCover"}],
            "import": ["tasks/normal.json", "tasks/CloseGamePC.json", "tasks/start.json"],
        }
        self.tasks = {
            "task": [
                {"name": "Collect", "entry": "Collect", "controller": ["Win32-Front", "PlayCover"]},
                {"name": "Another", "controller": ["AnotherWindows"]},
                {"name": "Touch", "controller": ["PlayCover"]},
                {"name": "Custom", "controller": [CONTROLLER]},
            ],
            "option": {"CollectOption": {"controller": ["Win32-Front"], "default_case": "Keep"}},
        }
        write_json(self.directory / "interface.json", self.interface)
        write_json(self.directory / "tasks/normal.json", self.tasks)
        write_json(self.directory / "tasks/CloseGamePC.json", {
            "task": [{"name": "CloseGamePC", "entry": "CloseGamePC", "controller": ["Win32-Front", CONTROLLER]}],
            "option": {"CloseGamePCSetting": {"controller": ["Win32-Front", CONTROLLER]}},
        })
        write_json(self.directory / "tasks/start.json", {
            "pretask": {"name": "LaunchGamePC", "controller": ["Win32-Front", CONTROLLER]},
        })
        (self.directory / "MaaEnd").write_bytes(b"original client")
        (self.directory / "agent").mkdir()
        (self.directory / "agent/go-service").write_bytes(b"original agent")
        (self.directory / "resource").mkdir()
        (self.directory / "resource/untouched").write_bytes(b"original resource")
        self.runtime = self.root / "EndPlayDesktop"
        (self.runtime / ".venv/bin").mkdir(parents=True)
        (self.runtime / ".venv/bin/python").touch()
        (self.runtime / "tools/EndPlayDesktop").mkdir(parents=True)
        (self.runtime / "tools/EndPlayDesktop/sidecar.py").touch()
        self.payload = self.root / "payload"
        self.payload.mkdir()
        for name in ("mxu", "go-service"):
            (self.payload / name).write_bytes(b"patched " + name.encode())
        self.manifest = {
            "format": 1, "maaend_version": "v2.33.0", "architecture": "arm64",
            "files": {name: {"path": name, "sha256": digest(self.payload / name)} for name in ("mxu", "go-service")},
        }
        write_json(self.payload / "manifest.json", self.manifest)
        self.backups = self.root / "backups"
        stack.enter_context(patch("tools.EndPlayDesktop.patch.running", return_value=False))
        self.verify = stack.enter_context(patch("tools.EndPlayDesktop.patch.verify_app"))
        stack.enter_context(patch("tools.EndPlayDesktop.patch.verify_original"))
        self.sign = stack.enter_context(patch("tools.EndPlayDesktop.patch.sign_app"))

    def snapshot(self) -> dict[str, bytes]:
        return {str(p.relative_to(self.app)): p.read_bytes() for p in self.app.rglob("*") if p.is_file()}

    def test_registers_one_controller_preserving_branding_and_existing_definitions(self) -> None:
        changes, _ = resource_changes(self.directory, self.runtime)
        interface = changes[Path("interface.json")]
        new = next(c for c in interface["controller"] if c["name"] == CONTROLLER)
        self.assertEqual(new["endplaydesktop"]["python"], str(self.runtime / ".venv/bin/python"))
        preserved = {**interface, "controller": [c for c in interface["controller"] if c["name"] != CONTROLLER]}
        self.assertEqual(preserved, self.interface)
        self.assertEqual(app_info(self.app)[0], self.info)

    def test_windows_tasks_and_options_expand_but_launch_and_close_are_excluded(self) -> None:
        changes, count = resource_changes(self.directory, self.runtime)
        tasks = changes[Path("tasks/normal.json")]
        for task in tasks["task"][:2]:
            self.assertIn(CONTROLLER, task["controller"])
        self.assertEqual(tasks["task"][2:], self.tasks["task"][2:])
        self.assertEqual(tasks["option"]["CollectOption"]["default_case"], "Keep")
        self.assertIn(CONTROLLER, tasks["option"]["CollectOption"]["controller"])
        close = changes[Path("tasks/CloseGamePC.json")]
        self.assertNotIn(CONTROLLER, close["task"][0]["controller"])
        self.assertNotIn(CONTROLLER, close["option"]["CloseGamePCSetting"]["controller"])
        self.assertNotIn(CONTROLLER, changes[Path("tasks/start.json")]["pretask"]["controller"])
        self.assertEqual(count, 6)

    def test_apply_is_repeatable_and_restore_recovers_exact_original_files(self) -> None:
        original = self.snapshot()
        result = apply_patch(self.app, self.payload, self.runtime, self.backups)
        self.assertEqual(result["status"], "applied")
        self.assertEqual((self.directory / "MaaEnd").read_bytes(), b"patched mxu")
        self.assertEqual((self.directory / "resource/untouched").read_bytes(), b"original resource")
        self.assertEqual(app_info(self.app)[0], self.info)
        self.assertTrue((self.app / RECEIPT).is_file())
        repeated = apply_patch(self.app, self.payload, self.runtime, self.backups)
        self.assertEqual(repeated["status"], "already_applied")
        self.assertEqual(len(list(self.backups.iterdir())), 1)
        restore(self.app, Path(result["backup"]))
        self.assertEqual(self.snapshot(), original)

    def test_signing_failure_preserves_original_app_and_keeps_backup(self) -> None:
        original = self.snapshot()
        self.sign.side_effect = OSError("signing failed")
        with self.assertRaisesRegex(OSError, "signing failed"):
            apply_patch(self.app, self.payload, self.runtime, self.backups)
        self.assertEqual(self.snapshot(), original)
        self.assertEqual(len(list(self.backups.iterdir())), 1)

    def test_rejects_unknown_payload_format_and_corrupt_payload_before_mutation(self) -> None:
        original = self.snapshot()
        self.manifest["format"] = 999
        write_json(self.payload / "manifest.json", self.manifest)
        with self.assertRaisesRegex(ValueError, "format"):
            apply_patch(self.app, self.payload, self.runtime, self.backups)
        self.manifest["format"] = 1
        write_json(self.payload / "manifest.json", self.manifest)
        (self.payload / "mxu").write_bytes(b"corrupted")
        with self.assertRaisesRegex(ValueError, "Corrupt"):
            load_payload(self.payload, self.app)
        (self.payload / "mxu").write_bytes(b"patched mxu")
        self.assertEqual(self.snapshot(), original)
        self.assertFalse(self.backups.exists())

    def test_rejects_import_escaping_the_app(self) -> None:
        self.interface["import"].append("../../../../outside.json")
        write_json(self.directory / "interface.json", self.interface)
        with self.assertRaisesRegex(ValueError, "escapes"):
            resource_changes(self.directory, self.runtime)

    def test_will_not_overwrite_an_edited_mxu_driver(self) -> None:
        source = self.root / "MXU"
        driver = source / "src-tauri/src/commands/endplaydesktop.rs"
        driver.parent.mkdir(parents=True)
        driver.write_bytes(b"local edits")
        with patch("tools.EndPlayDesktop.build_patch.commit", return_value="pinned"):
            with self.assertRaisesRegex(ValueError, "local edits"):
                prepare_mxu(source, {"mxu": {"commit": "pinned"}})
        self.assertEqual(driver.read_bytes(), b"local edits")

    def test_future_versions_and_changed_clients_are_not_blocked_by_a_baseline(self) -> None:
        self.info["CFBundleShortVersionString"] = "v999.0.0"
        (self.app / "Contents/Info.plist").write_bytes(plistlib.dumps(self.info))
        self.interface["version"] = "v999.0.0-rc.1"
        write_json(self.directory / "interface.json", self.interface)
        (self.directory / "MaaEnd").write_bytes(b"future upstream client")
        result = apply_patch(self.app, self.payload, self.runtime, self.backups)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["version"], "v999.0.0-rc.1")
        self.assertEqual(app_info(self.app)[0], self.info)


if __name__ == "__main__":
    unittest.main()
