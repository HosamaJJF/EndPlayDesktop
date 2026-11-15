"""Optional native MaaFramework wrapper for the standalone task CLI."""
from pathlib import Path

from maa.controller import CustomController

from .controller import EndPlayDesktopDevice


class EndPlayDesktopController(EndPlayDesktopDevice, CustomController):
    def __init__(self, endpoint: Path, maatools_address: str) -> None:
        EndPlayDesktopDevice.__init__(self, endpoint, maatools_address)
        CustomController.__init__(self)

    def inactive(self) -> bool:
        self.close()
        return True
