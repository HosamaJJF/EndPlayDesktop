"""Shared entry for the native patch application and its console sidecar."""
import json
import sys


def main() -> int:
    if sys.argv[1:3] == ["-m", "tools.EndPlayDesktop"]:
        from tools.EndPlayDesktop.cli import main as controller_main

        return controller_main(sys.argv[3:])
    if sys.argv[1:] == ["--runtime-check"]:
        import io
        import numpy as np
        from PIL import Image
        from tools.EndPlayDesktop.sidecar import dispatch
        from tools.EndPlayDesktop.lifecycle import launch_game

        data = io.BytesIO()
        Image.fromarray(np.zeros((2, 3, 3), dtype=np.uint8)).save(data, format="PNG")
        print(json.dumps({"frozen": bool(getattr(sys, "frozen", False)), "python": sys.version.split()[0],
                          "numpy": np.__version__, "png_bytes": len(data.getvalue()),
                          "sidecar_import": callable(dispatch), "lifecycle_import": callable(launch_game)}))
        return 0
    from tools.EndPlayDesktop.gui import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
