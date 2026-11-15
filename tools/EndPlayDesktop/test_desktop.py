from __future__ import annotations

import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from .desktop import (Distribution, backup_directories, cleanup_storage, clear_backups,
                      register_app, restore_backup, storage_lock)
from .patch import RECEIPT, write_json


class DistributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        default_app = patch("tools.EndPlayDesktop.desktop.DEFAULT_APP", self.root / "NotInstalled.app")
        default_app.start()
        self.addCleanup(default_app.stop)
        self.app = self.root / "DownloadedPatch.app"
        self.resources = self.app / "Contents/Resources"
        self.resources.mkdir(parents=True)
        executable = self.app / "Contents/MacOS/EndPlayDesktopRuntime"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"frozen launcher")
        source = self.resources / "runtime_source/tools/EndPlayDesktop/sidecar.py"
        source.parent.mkdir(parents=True)
        source.write_text("# actual packaged runtime source")
        write_json(self.resources / "distribution.json", {
            "format": 2, "version": "0.0.1", "build_id": "test-package", "payload": "desktop",
        })
        with zipfile.ZipFile(self.resources / "payloads.zip", "w") as archive:
            archive.writestr("desktop/mxu", b"original payload bytes")
            archive.writestr("desktop/manifest.json", '{"format":2,"files":{"mxu":{}}}')
        self.distribution = Distribution(self.app)
        self.support = self.root / "Application Support/EndPlayDesktop"

    def test_installed_runtime_survives_removal_of_downloaded_application(self) -> None:
        installed = self.distribution.install_runtime(self.support)
        self.assertEqual(self.distribution.install_runtime(self.support), installed)
        shutil.rmtree(self.app)
        self.assertEqual(installed.python.read_bytes(), b"frozen launcher")
        self.assertTrue((installed.project / "tools/EndPlayDesktop/sidecar.py").is_file())

    def test_controller_payload_is_independent_of_the_upstream_release(self) -> None:
        payload = self.distribution.install_payload(self.support)
        self.assertEqual((payload / "mxu").read_bytes(), b"original payload bytes")
        self.assertTrue((payload / "mxu").stat().st_mode & 0o111)
        self.assertFalse((payload / "go-service").exists())
        self.assertEqual(self.distribution.install_payload(self.support), payload)

    def test_payload_archive_cannot_escape_the_install_directory(self) -> None:
        with zipfile.ZipFile(self.resources / "payloads.zip", "w") as archive:
            archive.writestr("../../outside.txt", b"unexpected file")
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.distribution.install_payload(self.support)
        self.assertFalse((self.support / "outside.txt").exists())

    def install_build(self, build: str):
        write_json(self.resources / "distribution.json", {
            "format": 2, "version": "0.0.1", "build_id": build, "payload": "desktop",
        })
        return self.distribution.install_runtime(self.support)

    def target(self, name, runtime):
        app = self.root / name
        write_json(app / RECEIPT, {"format": 2, "runtime": str(runtime.project)})
        write_json(app / "Contents/MacOS/interface.json", {
            "controller": [{"name": "EndPlayDesktop", "endplaydesktop": {
                "python": str(runtime.python), "project_dir": str(runtime.project),
            }}],
        })
        return app

    def backup(self, name, app):
        backup = self.support / "backups" / name
        backup.mkdir(parents=True)
        shutil.copytree(app, backup / "MaaEnd.app")
        write_json(backup / "backup.json", {"format": 1, "app": str(app), "maaend_version": "test"})
        return backup

    def test_cleanup_reclaims_old_builds_of_the_same_version_and_payload_caches(self) -> None:
        old = self.install_build("old")
        current = self.install_build("new")
        app = self.target("MaaEnd.app", current)
        payload = self.distribution.install_payload(self.support)
        result = cleanup_storage(app, self.support)
        self.assertEqual(result, {"runtimes": 1, "payloads": 1})
        self.assertFalse(old.python.exists())
        self.assertTrue(current.python.is_file())
        self.assertFalse(payload.exists())
        self.assertEqual(cleanup_storage(app, self.support), {"runtimes": 0, "payloads": 0})

    def test_retained_backup_pins_its_runtime_until_backups_are_cleared(self) -> None:
        old = self.install_build("old")
        app = self.target("MaaEnd.app", old)
        backup = self.backup("before-update", app)
        current = self.install_build("new")
        self.target("MaaEnd.app", current)
        before = {str(p.relative_to(app)): p.read_bytes() for p in app.rglob("*") if p.is_file()}
        self.assertEqual(cleanup_storage(app, self.support)["runtimes"], 0)
        self.assertEqual(clear_backups(app, self.support)["deleted_backups"], 1)
        self.assertFalse(backup.exists())
        self.assertEqual(cleanup_storage(app, self.support)["runtimes"], 1)
        self.assertFalse(old.python.exists())
        self.assertTrue(current.python.exists())
        self.assertEqual({str(p.relative_to(app)): p.read_bytes() for p in app.rglob("*") if p.is_file()}, before)
        with self.assertRaisesRegex(ValueError, "没有找到"):
            restore_backup(app, self.support)

    def test_other_installations_remain_registered_after_clearing_backups(self) -> None:
        first = self.install_build("first")
        second = self.install_build("second")
        app = self.target("MaaEnd.app", first)
        other = self.target("Elsewhere/MaaEnd.app", second)
        self.backup("other-app", other)
        clear_backups(app, self.support)
        self.assertEqual(cleanup_storage(app, self.support)["runtimes"], 0)
        self.assertTrue(first.python.exists())
        self.assertTrue(second.python.exists())
        shutil.rmtree(other)
        self.assertEqual(cleanup_storage(app, self.support)["runtimes"], 1)

    def test_interface_reference_protects_runtime_without_a_receipt(self) -> None:
        runtime = self.install_build("active")
        app = self.target("MaaEnd.app", runtime)
        (app / RECEIPT).unlink()
        register_app(app, self.support)
        self.assertEqual(cleanup_storage(self.root / "NotInstalled.app", self.support)["runtimes"], 0)
        self.assertTrue(runtime.python.exists())

    def test_adapter_config_protects_runtime_if_an_updater_removes_the_receipt(self) -> None:
        runtime = self.install_build("adapter")
        app = self.target("MaaEnd.app", runtime)
        (app / RECEIPT).unlink()
        write_json(app / "Contents/MacOS/interface.json", {"controller": [{
            "name": "EndPlayDesktop", "type": "PlayCover", "playcover": {"uuid": "maa.endplaydesktop"}}]})
        write_json(app / "Contents/Resources/EndPlayDesktop/runtime.json", {
            "format": 1, "python": str(runtime.python), "project_dir": str(runtime.project)})
        self.assertEqual(cleanup_storage(app, self.support)["runtimes"], 0)
        self.assertTrue(runtime.python.exists())

    def test_cleanup_ignores_unrecognized_folders_and_symlinks(self) -> None:
        runtime = self.install_build("unused")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep").write_text("user data")
        (self.support / "runtimes/link").symlink_to(outside, target_is_directory=True)
        unknown = self.support / "runtimes/user-files"
        unknown.mkdir()
        (unknown / "keep").write_text("user data")
        (self.support / "backups").mkdir()
        (self.support / "backups/link").symlink_to(outside, target_is_directory=True)
        (self.support / "backups/notes").mkdir()
        (self.support / "backups/notes/keep").write_text("user data")
        self.assertEqual(clear_backups(self.root / "Missing.app", self.support)["deleted_backups"], 0)
        self.assertEqual(cleanup_storage(self.root / "Missing.app", self.support)["runtimes"], 1)
        self.assertFalse(runtime.python.exists())
        self.assertTrue((outside / "keep").is_file())
        self.assertTrue((unknown / "keep").is_file())
        self.assertTrue((self.support / "backups/notes/keep").is_file())

    def test_bad_installation_record_stops_cleanup_before_deleting_runtime(self) -> None:
        runtime = self.install_build("unused")
        write_json(self.support / "installations.json", {"format": 1, "apps": ["relative/app"]})
        with self.assertRaisesRegex(ValueError, "安装记录"):
            cleanup_storage(self.root / "Missing.app", self.support)
        self.assertTrue(runtime.python.exists())

    def test_bad_receipt_stops_cleanup_before_deleting_runtime(self) -> None:
        runtime = self.install_build("possibly-used")
        app = self.target("MaaEnd.app", runtime)
        (app / RECEIPT).write_text("broken json")
        with self.assertRaises(ValueError):
            cleanup_storage(app, self.support)
        self.assertTrue(runtime.python.exists())

    def test_legacy_agent_recovery_backup_cannot_be_cleared(self) -> None:
        runtime = self.install_build("legacy")
        app = self.target("MaaEnd.app", runtime)
        write_json(app / RECEIPT, {"format": 1})
        backup = self.backup("original-agent", app)
        with self.assertRaisesRegex(ValueError, "Agent"):
            clear_backups(app, self.support)
        self.assertTrue(backup.is_dir())

    def test_backup_parent_link_cannot_redirect_deletion(self) -> None:
        self.support.mkdir(parents=True)
        (self.support / "backups").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "符号链接"):
            backup_directories(self.support)
        self.assertTrue(self.app.is_dir())

    def test_concurrent_patchers_cannot_collect_each_others_runtime(self) -> None:
        with storage_lock(self.support):
            with self.assertRaisesRegex(ValueError, "另一个补丁工具"):
                with storage_lock(self.support):
                    self.fail("concurrent patcher entered")
        with storage_lock(self.support):
            pass


if __name__ == "__main__":
    unittest.main()
