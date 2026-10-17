from __future__ import annotations

import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from .desktop import Distribution
from .patch import write_json


class DistributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
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
            "version": "0.0.1", "build_id": "test-package", "payloads": ["v2.33.0"],
            "default_payload": "v2.33.0",
        })
        with zipfile.ZipFile(self.resources / "payloads.zip", "w") as archive:
            for name in ("mxu", "go-service"):
                archive.writestr("v2.33.0/" + name, b"original payload bytes")
        self.distribution = Distribution(self.app)
        self.support = self.root / "Application Support/EndPlayDesktop"

    def test_installed_runtime_survives_removal_of_downloaded_application(self) -> None:
        installed = self.distribution.install_runtime(self.support)
        self.assertEqual(self.distribution.install_runtime(self.support), installed)
        shutil.rmtree(self.app)
        self.assertEqual(installed.python.read_bytes(), b"frozen launcher")
        self.assertTrue((installed.project / "tools/EndPlayDesktop/sidecar.py").is_file())

    def test_future_target_versions_use_bundled_payload_without_a_whitelist(self) -> None:
        payload = self.distribution.install_payload("v999.0.0", self.support)
        self.assertEqual((payload / "mxu").read_bytes(), b"original payload bytes")
        self.assertTrue((payload / "go-service").stat().st_mode & 0o111)
        self.assertEqual(self.distribution.install_payload("v999.0.1", self.support), payload)

    def test_payload_archive_cannot_escape_the_install_directory(self) -> None:
        with zipfile.ZipFile(self.resources / "payloads.zip", "w") as archive:
            archive.writestr("../../outside.txt", b"unexpected file")
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.distribution.install_payload("v2.33.0", self.support)
        self.assertFalse((self.support / "outside.txt").exists())


if __name__ == "__main__":
    unittest.main()
