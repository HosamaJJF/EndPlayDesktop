from __future__ import annotations

import plistlib
import shutil
import struct
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from .build_patch import prepare_mxu
from .patch import (CONTROLLER, LEGACY_LIFECYCLE_TASKS, LEGACY_LIFECYCLE_PIPELINE, RECEIPT, app_info, apply_patch, digest, load_payload, sign_app,
                    read_json, resource_changes, restore, write_json)


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
            "import": ["tasks/normal.json", "tasks/CloseGamePC.json", "tasks/start.json",
                       "tasks/pretasks/LaunchGamePlayCover.json", "tasks/CloseGamePlayCover.json"],
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
        self.playcover_launch = {
            "pretask": {
                "name": "LaunchGamePlayCover", "label": "$pretask.LaunchGamePlayCover.label",
                "controller": ["PlayCover"], "exec": "agent/go-service",
                "args": ["--pretask", "LaunchGamePlayCover"],
                "option": ["LaunchGamePlayCoverAppPath", "LaunchGamePlayCoverLaunchDelay"],
            },
            "option": {
                "LaunchGamePlayCoverAppPath": {
                    "type": "input", "inputs": [{"name": "Path", "default": ""}],
                },
                "LaunchGamePlayCoverLaunchDelay": {
                    "type": "input", "inputs": [{"name": "Seconds", "default": "10", "verify": "[0-9]+"}],
                },
            },
        }
        self.playcover_close = {
            "task": [{"name": "CloseGamePlayCover", "entry": "CloseGamePlayCover",
                      "label": "$task.CloseGamePlayCover.label", "controller": ["PlayCover"],
                      "group": ["other_menu"]}],
        }
        write_json(self.directory / "tasks/pretasks/LaunchGamePlayCover.json", self.playcover_launch)
        write_json(self.directory / "tasks/CloseGamePlayCover.json", self.playcover_close)
        (self.directory / "MaaEnd").write_bytes(b"original client")
        (self.directory / "agent").mkdir()
        (self.directory / "agent/go-service").write_bytes(b"original agent")
        (self.directory / "agent/cpp-algo").write_bytes(b"original cpp agent")
        (self.directory / "maafw").mkdir()
        (self.directory / "maafw/libMaaFramework.dylib").write_bytes(b"original framework")
        (self.directory / "resource").mkdir()
        (self.directory / "resource/untouched").write_bytes(b"original resource")
        self.runtime = self.root / "EndPlayDesktop"
        (self.runtime / ".venv/bin").mkdir(parents=True)
        (self.runtime / ".venv/bin/python").touch()
        (self.runtime / "tools/EndPlayDesktop").mkdir(parents=True)
        (self.runtime / "tools/EndPlayDesktop/sidecar.py").touch()
        self.payload = self.root / "payload"
        self.payload.mkdir()
        for name in ("mxu",):
            (self.payload / name).write_bytes(b"patched " + name.encode())
        self.manifest = {
            "format": 2, "tested_maaend_version": "v2.33.0", "architecture": "arm64",
            "files": {"mxu": {"path": "mxu", "sha256": digest(self.payload / "mxu")}},
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

    def test_bundled_launcher_works_without_a_virtual_environment(self) -> None:
        (self.runtime / ".venv/bin/python").unlink()
        executable = self.root / "Managed Runtime/EndPlayDesktopRuntime"
        executable.parent.mkdir()
        executable.write_bytes(b"frozen runtime")
        result = apply_patch(self.app, self.payload, self.runtime, self.backups, executable)
        self.assertEqual(result["status"], "applied")
        interface = read_json(self.directory / "interface.json")
        controller = next(c for c in interface["controller"] if c["name"] == CONTROLLER)
        self.assertEqual(controller["endplaydesktop"]["python"], str(executable))

    def test_unchanged_legacy_driver_upgrades_with_only_the_controller_patch(self) -> None:
        source = self.root / "MXU"
        driver = source / "src-tauri/src/commands/endplaydesktop.rs"
        driver.parent.mkdir(parents=True)
        driver.write_bytes(b"known previous driver")
        with patch("tools.EndPlayDesktop.build_patch.LEGACY_DRIVERS", {digest(driver)}), \
                patch("tools.EndPlayDesktop.build_patch.source_patch_applied", return_value=False), \
                patch("tools.EndPlayDesktop.build_patch.apply_source_patch") as apply:
            prepare_mxu(source, {"mxu": {}})
        apply.assert_called_once_with(source, Path(__file__).resolve().parents[2] / "patches/mxu.patch")
        self.assertIn(b"fn stop_app", driver.read_bytes())

    def test_old_mxu_lifecycle_patch_is_reversed_before_preparing_controller(self) -> None:
        source = self.root / "MXU"
        driver = source / "src-tauri/src/commands/endplaydesktop.rs"
        driver.parent.mkdir(parents=True)
        expected = Path(__file__).resolve().parents[2] / "patches/mxu/controller.rs"
        shutil.copy2(expected, driver)
        with patch("tools.EndPlayDesktop.build_patch.source_patch_applied", return_value=True), \
                patch("tools.EndPlayDesktop.build_patch.run") as run, \
                patch("tools.EndPlayDesktop.build_patch.apply_source_patch") as apply:
            prepare_mxu(source, {"mxu": {}})
        run.assert_called_once_with("git", "apply", "--reverse",
                                    str(expected.parents[1] / "legacy/mxu-lifecycle.patch"), cwd=source)
        apply.assert_called_once_with(source, expected.parents[1] / "mxu.patch")

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
        self.assertEqual(count, 8)

    def test_reuses_upstream_playcover_lifecycle_without_adding_tasks_or_resources(self) -> None:
        changes, _ = resource_changes(self.directory, self.runtime)
        launch = changes[Path("tasks/pretasks/LaunchGamePlayCover.json")]
        close = changes[Path("tasks/CloseGamePlayCover.json")]
        self.assertEqual(launch["pretask"]["controller"], ["PlayCover", CONTROLLER])
        self.assertEqual(close["task"][0]["controller"], ["PlayCover", CONTROLLER])
        launch["pretask"]["controller"].remove(CONTROLLER)
        close["task"][0]["controller"].remove(CONTROLLER)
        self.assertEqual(launch, self.playcover_launch)
        self.assertEqual(close, self.playcover_close)
        self.assertTrue(all((self.directory / path).is_file() for path in changes))
        self.assertNotIn(LEGACY_LIFECYCLE_TASKS, changes)
        self.assertNotIn(LEGACY_LIFECYCLE_PIPELINE, changes)
        controller = next(c for c in changes[Path("interface.json")]["controller"] if c["name"] == CONTROLLER)
        self.assertNotIn("attach_resource_path", controller)

    def test_playcover_lifecycle_uses_declared_controller_names_and_expands_option_filters(self) -> None:
        self.interface["controller"][-1]["name"] = "RenamedPlayCover"
        write_json(self.directory / "interface.json", self.interface)
        self.playcover_launch["pretask"]["controller"] = ["RenamedPlayCover"]
        option = self.playcover_launch["option"]["LaunchGamePlayCoverAppPath"]
        option["controller"] = ["RenamedPlayCover"]
        option["cases"] = [{"name": "Default", "controller": ["RenamedPlayCover"]}]
        write_json(self.directory / "tasks/pretasks/LaunchGamePlayCover.json", self.playcover_launch)
        self.playcover_close["task"][0]["controller"] = ["RenamedPlayCover"]
        write_json(self.directory / "tasks/CloseGamePlayCover.json", self.playcover_close)
        changes, _ = resource_changes(self.directory, self.runtime)
        launch = changes[Path("tasks/pretasks/LaunchGamePlayCover.json")]
        self.assertEqual(launch["pretask"]["controller"], ["RenamedPlayCover", CONTROLLER])
        option = launch["option"]["LaunchGamePlayCoverAppPath"]
        self.assertEqual(option["controller"], ["RenamedPlayCover", CONTROLLER])
        self.assertEqual(option["cases"][0]["controller"], ["RenamedPlayCover", CONTROLLER])
        self.assertEqual(changes[Path("tasks/CloseGamePlayCover.json")]["task"][0]["controller"],
                         ["RenamedPlayCover", CONTROLLER])

    def test_reapplying_removes_legacy_lifecycle_and_restore_recovers_it(self) -> None:
        self.interface["import"].append(LEGACY_LIFECYCLE_TASKS.as_posix())
        self.interface["controller"].append({
            "name": CONTROLLER, "type": CONTROLLER,
            "attach_resource_path": ["./resource_endplaydesktop"],
        })
        write_json(self.directory / "interface.json", self.interface)
        write_json(self.directory / LEGACY_LIFECYCLE_TASKS, {
            "pretask": {"name": "LaunchGameEndPlayDesktop", "controller": [CONTROLLER]},
            "task": [{"name": "CloseGameEndPlayDesktop", "controller": [CONTROLLER]}],
        })
        write_json(self.directory / LEGACY_LIFECYCLE_PIPELINE, {"EndPlayDesktopCloseGame": {"action": "StopApp"}})
        original = self.snapshot()
        result = apply_patch(self.app, self.payload, self.runtime, self.backups)
        self.assertEqual(result["status"], "applied")
        interface = read_json(self.directory / "interface.json")
        self.assertNotIn(LEGACY_LIFECYCLE_TASKS.as_posix(), interface["import"])
        self.assertFalse((self.directory / LEGACY_LIFECYCLE_TASKS).exists())
        self.assertFalse((self.directory / LEGACY_LIFECYCLE_PIPELINE).exists())
        controller = next(c for c in interface["controller"] if c["name"] == CONTROLLER)
        self.assertNotIn("attach_resource_path", controller)
        signed = {path.relative_to(self.sign.call_args.args[0] / "Contents/MacOS")
                  for path in self.sign.call_args.args[1]}
        self.assertNotIn(LEGACY_LIFECYCLE_TASKS, signed)
        self.assertNotIn(LEGACY_LIFECYCLE_PIPELINE, signed)
        self.assertIn(CONTROLLER, read_json(self.directory / "tasks/pretasks/LaunchGamePlayCover.json")["pretask"]["controller"])
        self.assertIn(CONTROLLER, read_json(self.directory / "tasks/CloseGamePlayCover.json")["task"][0]["controller"])
        self.assertEqual(apply_patch(self.app, self.payload, self.runtime, self.backups)["status"], "already_applied")
        restore(self.app, Path(result["backup"]))
        self.assertEqual(self.snapshot(), original)

    def test_apply_is_repeatable_and_restore_recovers_exact_original_files(self) -> None:
        original = self.snapshot()
        result = apply_patch(self.app, self.payload, self.runtime, self.backups)
        self.assertEqual(result["status"], "applied")
        self.assertEqual((self.directory / "MaaEnd").read_bytes(), b"patched mxu")
        self.assertEqual((self.directory / "agent/go-service").read_bytes(), b"original agent")
        self.assertEqual((self.directory / "agent/cpp-algo").read_bytes(), b"original cpp agent")
        self.assertEqual((self.directory / "maafw/libMaaFramework.dylib").read_bytes(), b"original framework")
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

    def test_generated_records_are_sealed_without_resigning_executables(self) -> None:
        config = self.directory / "config/maa_option.json"
        record = self.directory / "debug/record/random_salt.txt"
        executable = self.directory / "debug/native-helper"
        for path, data in [(config, b"{}"), (record, b"test salt"), (executable, b"\xcf\xfa\xed\xfe" + b"native code")]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        before = self.snapshot()
        with patch("tools.EndPlayDesktop.patch.subprocess.run") as run:
            run.return_value.returncode = 0
            sign_app(self.app, [])
        signed = [call.args[0][-1] for call in run.call_args_list]
        self.assertIn(str(config), signed)
        self.assertIn(str(record), signed)
        self.assertNotIn(str(executable), signed)
        self.assertNotIn(str(self.directory / "agent/go-service"), signed)
        self.assertEqual(self.snapshot(), before)

    def test_rejects_unknown_payload_format_and_corrupt_payload_before_mutation(self) -> None:
        original = self.snapshot()
        self.manifest["format"] = 999
        write_json(self.payload / "manifest.json", self.manifest)
        with self.assertRaisesRegex(ValueError, "format"):
            apply_patch(self.app, self.payload, self.runtime, self.backups)
        self.manifest["format"] = 2
        write_json(self.payload / "manifest.json", self.manifest)
        (self.payload / "mxu").write_bytes(b"corrupted")
        with self.assertRaisesRegex(ValueError, "Corrupt"):
            load_payload(self.payload)
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
        (self.directory / "agent/go-service").write_bytes(b"future upstream agent with new operations")
        result = apply_patch(self.app, self.payload, self.runtime, self.backups)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["version"], "v999.0.0-rc.1")
        self.assertEqual(app_info(self.app)[0], self.info)
        self.assertEqual((self.directory / "agent/go-service").read_bytes(),
                         b"future upstream agent with new operations")

    def test_reapplying_after_an_upstream_update_keeps_new_agents_and_tasks(self) -> None:
        apply_patch(self.app, self.payload, self.runtime, self.backups)
        # Simulate an updater retaining the receipt while replacing upstream files.
        self.interface["version"] = "v2.36.0-beta.1"
        write_json(self.directory / "interface.json", self.interface)
        write_json(self.directory / "tasks/normal.json", {
            "task": [{"name": "NewUpstreamTask", "controller": ["Win32-Front"]}],
            "option": {"MinimumPrice": {"operation": "configure_minimum_price"}},
        })
        (self.directory / "MaaEnd").write_bytes(b"new upstream client")
        (self.directory / "agent/go-service").write_bytes(b"new upstream agent")
        result = apply_patch(self.app, self.payload, self.runtime, self.backups)
        self.assertEqual(result["status"], "applied")
        self.assertEqual((self.directory / "agent/go-service").read_bytes(), b"new upstream agent")
        tasks = read_json(self.directory / "tasks/normal.json")
        self.assertIn(CONTROLLER, tasks["task"][0]["controller"])
        self.assertEqual(tasks["option"]["MinimumPrice"]["operation"], "configure_minimum_price")

    def test_reapplies_when_only_the_upstream_client_was_replaced(self) -> None:
        apply_patch(self.app, self.payload, self.runtime, self.backups)
        (self.directory / "MaaEnd").write_bytes(b"updated client with unchanged resources")
        result = apply_patch(self.app, self.payload, self.runtime, self.backups)
        self.assertEqual(result["status"], "applied")
        self.assertEqual((self.directory / "MaaEnd").read_bytes(), b"patched mxu")

    def test_resigning_the_app_does_not_create_another_backup(self) -> None:
        header = struct.pack("<IiiIIIII", 0xFEEDFACF, 0x100000C, 0, 2, 1, 24, 0, 0)
        executable = header + struct.pack("<II16s", 0x1B, 24, b"build identifier")
        (self.payload / "mxu").write_bytes(executable + b"payload signature")
        self.manifest["files"]["mxu"]["sha256"] = digest(self.payload / "mxu")
        write_json(self.payload / "manifest.json", self.manifest)

        def sign(app: Path, resources: list[Path]) -> None:
            (app / "Contents/MacOS/MaaEnd").write_bytes(executable + b"app signature")

        self.sign.side_effect = sign
        apply_patch(self.app, self.payload, self.runtime, self.backups)
        repeated = apply_patch(self.app, self.payload, self.runtime, self.backups)
        self.assertEqual(repeated["status"], "already_applied")
        self.assertEqual(len(list(self.backups.iterdir())), 1)

    def legacy_install(self) -> Path:
        donor = self.root / "legacy-backup/MaaEnd.app"
        donor.parent.mkdir()
        shutil.copytree(self.app, donor)
        (self.directory / "agent/go-service").write_bytes(b"outdated patched agent")
        write_json(self.app / RECEIPT, {
            "format": 1, "maaend_version": "v2.33.0", "backup": str(donor.parent),
        })
        return donor

    def test_legacy_patch_recovers_the_same_release_agent_from_backup(self) -> None:
        self.legacy_install()
        result = apply_patch(self.app, self.payload, self.runtime, self.backups)
        self.assertTrue(result["recovered_agent"])
        self.assertEqual((self.directory / "agent/go-service").read_bytes(), b"original agent")
        self.assertEqual(read_json(self.app / RECEIPT)["format"], 2)

    def test_legacy_patch_follows_backups_past_an_earlier_patched_app(self) -> None:
        donor = self.legacy_install()
        intermediate = self.root / "intermediate/MaaEnd.app"
        intermediate.parent.mkdir()
        shutil.copytree(self.app, intermediate)
        receipt = read_json(self.app / RECEIPT)
        receipt["backup"] = str(intermediate.parent)
        write_json(self.app / RECEIPT, receipt)
        result = apply_patch(self.app, self.payload, self.runtime, self.backups)
        self.assertTrue(result["recovered_agent"])
        self.assertEqual((self.directory / "agent/go-service").read_bytes(),
                         (donor / "Contents/MacOS/agent/go-service").read_bytes())

    def test_legacy_patch_cannot_keep_a_stale_agent_or_restore_another_release(self) -> None:
        donor = self.legacy_install()
        for mode in ("wrong_version", "missing", "cycle"):
            with self.subTest(mode=mode):
                if mode == "wrong_version":
                    interface = read_json(donor / "Contents/MacOS/interface.json")
                    interface["version"] = "v2.32.0"
                    write_json(donor / "Contents/MacOS/interface.json", interface)
                elif mode == "missing":
                    shutil.rmtree(donor)
                else:
                    receipt = read_json(self.app / RECEIPT)
                    receipt["backup"] = str(self.root)
                    write_json(self.app / RECEIPT, receipt)
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, "官方 MaaEnd"):
                    apply_patch(self.app, self.payload, self.runtime, self.backups)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(self.backups.exists())

    def test_old_and_agent_containing_payloads_are_rejected_before_mutation(self) -> None:
        before = self.snapshot()
        for file_format in (1, 2):
            with self.subTest(file_format=file_format):
                self.manifest["format"] = file_format
                self.manifest["files"]["go-service"] = {"path": "go-service", "sha256": "unused"}
                write_json(self.payload / "manifest.json", self.manifest)
                with self.assertRaises(ValueError):
                    apply_patch(self.app, self.payload, self.runtime, self.backups)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(self.backups.exists())


if __name__ == "__main__":
    unittest.main()
