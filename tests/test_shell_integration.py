"""Real Windows registry/shortcut checks confined to disposable destinations."""
import json
from pathlib import Path
import sys
import uuid

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows shell integration")


@pytest.fixture
def integration(tmp_path, monkeypatch):
    import winreg
    from tangerine import shell_integration as shell

    original_root = winreg.HKEY_CURRENT_USER
    scratch = rf"Software\Tangerine\Tests\{uuid.uuid4().hex}"
    root = winreg.CreateKey(original_root, scratch)
    monkeypatch.setattr(winreg, "HKEY_CURRENT_USER", root)
    monkeypatch.setattr(shell, "_sendto_dir", lambda: tmp_path / "SendTo")
    monkeypatch.setattr(shell.paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(shell, "_notify", lambda: None)
    exe = tmp_path / "Tangerine.exe"
    exe.write_bytes(b"fixture; never executed")
    dll = tmp_path / "_internal/shell/TangerineShell.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"fixture; never loaded")
    try:
        yield shell, exe
    finally:
        # _delete_tree resolves all paths beneath the temporary registry root.
        with winreg.OpenKey(root, "") as key:
            children = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
        for child in children:
            shell._delete_tree(child)
        root.Close()
        winreg.DeleteKey(original_root, scratch)


def test_registration_readback_and_owned_uninstall(integration):
    import winreg
    from comtypes.client import CreateObject
    shell, exe = integration
    result = shell.register_shell(exe)
    assert shell._read(shell.HANDLER_KEY) == shell.CLSID
    assert Path(shell._read(shell.CONFIG_KEY, "ExecutablePath")) == exe
    assert Path(shell._read(shell.CLASS_KEY + r"\InprocServer32")) == Path(result["dll"])
    com = CreateObject("WScript.Shell", dynamic=True)
    for filename, arguments in shell.SHORTCUTS.items():
        link = com.CreateShortcut(str(Path(result["sendto"]) / filename))
        assert Path(link.TargetPath) == exe and link.Arguments == arguments
    shell.register_shell(exe)  # Repeated repair is safe.
    shell.unregister_shell()
    assert shell._read(shell.HANDLER_KEY) is None
    assert not list(Path(result["sendto"]).glob("*.lnk"))


def test_foreign_registration_is_preserved(integration):
    import winreg
    shell, exe = integration
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, shell.HANDLER_KEY) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "foreign-handler")
    with pytest.raises(RuntimeError, match="another application"):
        shell.register_shell(exe)
    assert shell._read(shell.HANDLER_KEY) == "foreign-handler"
    assert not shell._sendto_dir().exists()
    shell.unregister_shell()
    assert shell._read(shell.HANDLER_KEY) == "foreign-handler"


def test_migration_backs_up_only_owned_standalone_keys(integration):
    import winreg
    shell, exe = integration
    old = r"Software\Classes\*\shellex\ContextMenuHandlers\CrisImageToPdf"
    foreign = r"Software\Classes\SystemFileAssociations\image\shell\CrisImageToPdf"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, old) as key:
        winreg.SetValueEx(key, "CrisManagedBy", 0, winreg.REG_SZ, "CrisImageToPdfContextMenu")
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "old-handler")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, foreign) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "foreign-data")
    shell.register_shell(exe)
    backups = list((exe.parent / "backups").glob("standalone-shell-*.json"))
    assert len(backups) == 1
    saved = json.loads(backups[0].read_text(encoding="utf-8"))
    assert list(saved) == [old]
    assert any(value[0:2] == ["", "old-handler"] for value in saved[old]["values"])
    assert shell._read(old) is None and shell._read(foreign) == "foreign-data"
