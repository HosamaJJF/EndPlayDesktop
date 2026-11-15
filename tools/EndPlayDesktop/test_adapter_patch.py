from __future__ import annotations

import json
import plistlib
import shutil
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from . import test_patch
from .agent_launch import agent_environment, exec_agent
from .adapter_patch import ADAPTER, CONFIG, LAUNCHER
from .patch import CONTROLLER, RECEIPT, apply_patch, digest, read_json, restore, running, write_json


class AdapterPatchTests(unittest.TestCase):
    def setUp(self):
        test_patch.AppPatchTests.setUp(self)
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.sign = stack.enter_context(patch("tools.EndPlayDesktop.adapter_patch.sign_app"))
        stack.enter_context(patch("tools.EndPlayDesktop.adapter_patch.sign_upstream"))
        stack.enter_context(patch("tools.EndPlayDesktop.adapter_patch.verify_app"))
        stack.enter_context(patch("tools.EndPlayDesktop.adapter_patch.verify_original"))
        self.legacy_manifest = self.manifest
        self.manifest = {"format": 3, "architecture": "arm64", "files": {}}
        for name in ("controller", "launcher"):
            (self.payload / name).write_bytes(name.encode())
            self.manifest["files"][name] = {"path": name, "sha256": digest(self.payload / name)}
        write_json(self.payload / "manifest.json", self.manifest)
        self.interface["agent"] = [{"child_exec": "./agent/go-service", "child_args": ["--upstream-option"]},
                                   {"child_exec": "./agent/cpp-algo"}]
        write_json(self.directory / "interface.json", self.interface)

    snapshot = test_patch.AppPatchTests.snapshot

    def apply(self):
        return apply_patch(self.app, self.payload, self.runtime, self.backups)

    def test_external_adapter_keeps_upstream_binaries_and_restores_exact_original(self):
        original = self.snapshot()
        result = self.apply()
        self.assertTrue(result["preserves_upstream_mxu"])
        self.assertEqual((self.directory / "MaaEnd").read_bytes(), b"original client")
        for name in ("agent/go-service", "agent/cpp-algo", "maafw/libMaaFramework.dylib", "resource/untouched"):
            self.assertEqual((self.directory / name).read_bytes(), original["Contents/MacOS/" + name])
        self.assertEqual(plistlib.loads((self.app / "Contents/Info.plist").read_bytes()),
                         {**self.info, "CFBundleExecutable": LAUNCHER})
        self.assertEqual((self.app / ADAPTER).read_bytes(), b"controller")
        self.assertEqual(read_json(self.app / CONFIG)["upstream_executable"], "MaaEnd")
        interface = read_json(self.directory / "interface.json")
        controller = next(c for c in interface["controller"] if c["name"] == CONTROLLER)
        self.assertEqual(controller["type"], "PlayCover")
        self.assertEqual(controller["playcover"]["uuid"], "maa.endplaydesktop")
        for agent, original_agent in zip(interface["agent"], self.interface["agent"]):
            self.assertEqual(agent["endplaydesktop_original"], original_agent)
            self.assertEqual(agent["child_args"][4:], [original_agent["child_exec"], *original_agent.get("child_args", [])])
        self.assertEqual(self.apply()["status"], "already_applied")
        self.assertEqual(len(list(self.backups.iterdir())), 1)
        restore(self.app, Path(result["backup"]))
        self.assertEqual(self.snapshot(), original)

    def test_upstream_update_keeps_the_new_mxu_even_if_receipt_survives(self):
        self.apply()
        (self.app / "Contents/Info.plist").write_bytes(plistlib.dumps(self.info))
        self.interface["version"] = "v999.0.0"
        write_json(self.directory / "interface.json", self.interface)
        (self.directory / "MaaEnd").write_bytes(b"new official MXU")
        result = self.apply()
        self.assertTrue(result["preserves_upstream_mxu"])
        self.assertFalse(result["recovered_mxu"])
        self.assertEqual((self.directory / "MaaEnd").read_bytes(), b"new official MXU")

    def test_reapplying_after_receipt_removal_recovers_upstream_name_from_adapter_config(self):
        self.apply()
        (self.app / RECEIPT).unlink()
        self.assertEqual(self.apply()["status"], "applied")
        self.assertEqual((self.directory / "MaaEnd").read_bytes(), b"original client")
        self.assertEqual(read_json(self.app / RECEIPT)["upstream_executable"], "MaaEnd")

    def test_legacy_mxu_is_recovered_from_matching_original_backup(self):
        write_json(self.payload / "manifest.json", self.legacy_manifest)
        apply_patch(self.app, self.payload, self.runtime, self.backups, replace_mxu=True)
        self.assertEqual((self.directory / "MaaEnd").read_bytes(), b"patched mxu")
        write_json(self.payload / "manifest.json", self.manifest)
        result = self.apply()
        self.assertTrue(result["recovered_mxu"])
        self.assertEqual((self.directory / "MaaEnd").read_bytes(), b"original client")
        self.assertEqual(read_json(self.app / RECEIPT)["format"], 3)

    def test_missing_original_mxu_backup_requires_reinstall_without_mutating_app(self):
        write_json(self.payload / "manifest.json", self.legacy_manifest)
        apply_patch(self.app, self.payload, self.runtime, self.backups, replace_mxu=True)
        write_json(self.payload / "manifest.json", self.manifest)
        shutil.rmtree(self.backups)
        original = self.snapshot()
        with self.assertRaisesRegex(ValueError, "重新安装"):
            self.apply()
        self.assertEqual(self.snapshot(), original)
        self.assertFalse(self.backups.exists())

    def test_stale_legacy_receipt_does_not_restore_an_old_mxu_over_an_upstream_update(self):
        write_json(self.app / RECEIPT, {"format": 2, "maaend_version": "v1.0.0", "backup": "/missing"})
        self.assertFalse(self.apply()["recovered_mxu"])
        self.assertEqual((self.directory / "MaaEnd").read_bytes(), b"original client")

    def test_signing_failure_preserves_original_and_recovery_backup(self):
        original = self.snapshot()
        self.sign.side_effect = ValueError("signing failure")
        with self.assertRaisesRegex(ValueError, "signing failure"):
            self.apply()
        self.assertEqual(self.snapshot(), original)
        self.assertEqual(len(list(self.backups.iterdir())), 1)

    def test_running_detection_matches_actual_upstream_process_behind_launcher(self):
        self.apply()
        with patch("tools.EndPlayDesktop.patch.subprocess.check_output", return_value=str(self.directory / "MaaEnd")):
            self.assertTrue(running(self.app))


class AgentLaunchTests(unittest.TestCase):
    def test_only_endplaydesktop_uses_desktop_kind_and_injection_is_removed(self):
        for name, kind in (("EndPlayDesktop", "MacOS"), ("PlayCover", "PlayCover")):
            with self.subTest(name=name):
                source = {"PI_CONTROLLER": json.dumps({"name": name, "type": "PlayCover"}),
                          "ENDPLAYDESKTOP_ADAPTER_LOADED": "1",
                          "DYLD_INSERT_LIBRARIES": "/adapter", "ENDPLAYDESKTOP_CONFIG": "/config", "PATH": "/usr/bin"}
                result = agent_environment(source)
                self.assertEqual(json.loads(result["PI_CONTROLLER"])["type"], kind)
                self.assertNotIn("DYLD_INSERT_LIBRARIES", result)
                self.assertEqual(result["PATH"], source["PATH"])
                self.assertEqual(json.loads(source["PI_CONTROLLER"])["type"], "PlayCover")

    def test_missing_adapter_aborts_before_any_agent_can_run_mobile_pipelines(self):
        with self.assertRaisesRegex(ValueError, "适配层未加载"):
            agent_environment({"PI_CONTROLLER": '{"name":"EndPlayDesktop","type":"PlayCover"}'})

    def test_agent_arguments_and_ipc_identifier_are_forwarded_without_shell_interpolation(self):
        args = ["--", "./agent/go-service", "an argument with spaces", "ipc:///tmp/maa.sock"]
        with patch("tools.EndPlayDesktop.agent_launch.os.execvpe") as execute:
            exec_agent(args)
        self.assertEqual(execute.call_args.args[:2], (args[1], args[1:]))
