"""Exercise upstream delegate forwarding and hidden window recovery."""
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.EndPlayDesktop.macho import add_adapter_dependency


def main():
    client, adapter = map(Path, sys.argv[1:])
    with tempfile.TemporaryDirectory(prefix="epd lifecycle ") as temporary:
        app = Path(temporary) / "Lifecycle.app"
        binary = app / "Contents/MacOS/upstream-client"
        resources = app / "Contents/Resources/EndPlayDesktop"
        binary.parent.mkdir(parents=True)
        resources.mkdir(parents=True)
        shutil.copy2(client, binary)
        shutil.copy2(adapter, resources / adapter.name)
        (resources / "runtime.json").write_text("{}")
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
            "CFBundleExecutable": binary.name, "CFBundleIdentifier": "test.endplaydesktop.lifecycle",
            "CFBundlePackageType": "APPL",
        }))
        add_adapter_dependency(binary)
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("DYLD_", "ENDPLAYDESKTOP_"))}
        subprocess.run([str(binary)], check=True, env=env, timeout=15)


if __name__ == "__main__":
    main()
