"""User report destinations, independent of source roots and the working tree."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def documents_directory() -> Path:
    """Resolve the current OS user's Documents, including Windows redirection."""
    if os.name == "nt":
        import ctypes
        from uuid import UUID

        # FOLDERID_Documents, resolved by Windows rather than a guessed profile path.
        folder_id = ctypes.create_string_buffer(UUID("FDD39AD0-238F-46AF-ADB4-6C85480369C7").bytes_le)
        result = ctypes.c_wchar_p()
        shell = ctypes.WinDLL("shell32")
        get_folder = shell.SHGetKnownFolderPath
        get_folder.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                               ctypes.POINTER(ctypes.c_wchar_p)]
        get_folder.restype = ctypes.c_long
        free = ctypes.WinDLL("ole32").CoTaskMemFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = None
        # KF_FLAG_DONT_VERIFY lets our writer create a configured folder that
        # does not exist yet (common on a fresh Windows user profile).
        status = get_folder(ctypes.byref(folder_id), 0x4000, None, ctypes.byref(result))
        try:
            if status != 0 or not result.value:
                raise ValueError("Windows Documents is unavailable; provide --out REPORT_DIR")
            return Path(result.value)
        finally:
            if result:
                free(ctypes.cast(result, ctypes.c_void_p))
    if sys.platform.startswith("linux") and shutil.which("xdg-user-dir"):
        try:
            result = subprocess.run(["xdg-user-dir", "DOCUMENTS"], capture_output=True,
                                    text=True, timeout=5, check=False)
            path = Path(result.stdout.strip())
            if result.returncode == 0 and path.is_absolute():
                return path
        except (OSError, subprocess.TimeoutExpired):
            pass
    return Path.home() / "Documents"


def new_report_directory() -> Path:
    root = documents_directory() / "Agent Analysis"
    root.mkdir(parents=True, exist_ok=True)
    # A timestamp plus mkdtemp's suffix prevents concurrent runs from overwriting.
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    return Path(tempfile.mkdtemp(prefix=stamp + "_", dir=root))
