"""The test suite must never reach a KiCad the developer has open.

With KiCad running, the interface's runtime IPC switch connects to it, and
tests then run against the developer's live session instead of the stubs.
"""

import kicad_interface
from kicad_api import ipc_backend


def test_runtime_ipc_switch_never_contacts_live_kicad(monkeypatch) -> None:
    contacted = []

    def fake_connect(self) -> bool:
        contacted.append(True)
        raise RuntimeError("test contacted a live KiCad")

    monkeypatch.setattr(
        kicad_interface.KiCADProcessManager, "is_running", staticmethod(lambda: True)
    )
    monkeypatch.setattr(ipc_backend.IPCBackend, "connect", fake_connect)
    interface = kicad_interface.KiCADInterface.__new__(kicad_interface.KiCADInterface)
    interface.use_ipc = False
    interface.ipc_backend = None

    assert interface._try_enable_ipc_backend() is False
    assert contacted == []
