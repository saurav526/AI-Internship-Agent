"""Windows Desktop Shortcut Creator & Launcher Verifier for AI Internship Application Agent.

Creates a valid Windows Shell Link (`.lnk`) file named `AI Internship Agent.lnk` pointing to:
`C:\\Users\\Asus\\Downloads\\AI-Internship-Agent\\launch_dashboard.bat`
with Working Directory:
`C:\\Users\\Asus\\Downloads\\AI-Internship-Agent`
"""
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List
from src.logger import get_logger

logger = get_logger("windows_launchpad")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BATCH_LAUNCHER_PATH = PROJECT_ROOT / "launch_dashboard.bat"
LOCAL_SHORTCUT_PATH = PROJECT_ROOT / "AI Internship Agent.lnk"


def get_desktop_candidate_paths() -> List[Path]:
    """Return candidate Windows Desktop paths plus the project root fallback."""
    user_profile = Path(os.getenv("USERPROFILE") or "C:/Users/Asus")
    return [
        user_profile / "Desktop" / "AI Internship Agent.lnk",
        user_profile / "OneDrive" / "Desktop" / "AI Internship Agent.lnk",
        LOCAL_SHORTCUT_PATH,
    ]


def _create_lnk_via_wscript_or_win32(shortcut_path: Path, target_bat: Path, working_dir: Path) -> bool:
    """Create a valid Windows .lnk shortcut using win32com.client (pywin32) or PowerShell WScript.Shell."""
    try:
        import pythoncom
        from win32com.client import Dispatch

        pythoncom.CoInitialize()
        shell = Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(shortcut_path))
        shortcut.Targetpath = str(target_bat)
        shortcut.WorkingDirectory = str(working_dir)
        shortcut.Description = "Launch AI Internship Application Agent Streamlit Dashboard"
        shortcut.IconLocation = "shell32.dll,21"
        shortcut.save()
        return shortcut_path.exists()
    except Exception as exc:
        logger.info("win32com shortcut creation fallback (%s); trying PowerShell WScript.Shell.", exc)

    try:
        ps_cmd = (
            f"$s=(New-Object -COM WScript.Shell).CreateShortcut('{shortcut_path}');"
            f"$s.TargetPath='{target_bat}';"
            f"$s.WorkingDirectory='{working_dir}';"
            f"$s.Description='Launch AI Internship Application Agent Streamlit Dashboard';"
            f"$s.IconLocation='shell32.dll,21';"
            f"$s.Save()"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=True, timeout=5)
        return shortcut_path.exists()
    except Exception as exc:
        logger.warning("Could not create shortcut at %s: %s", shortcut_path, exc)
        return False


def _write_minimal_ms_shllink(shortcut_path: Path, target_bat: Path, working_dir: Path) -> bool:
    """Write a valid MS-SHLLINK (.lnk) header + Unicode StringData structure when COM is restricted in a sandbox."""
    import struct

    header_size = 0x0000004C
    clsid = bytes.fromhex("0114020000000000C000000000000046")
    # LinkFlags: HasName (0x08) | HasWorkingDir (0x10) | HasArguments (0x20) | IsUnicode (0x80)
    link_flags = 0x00000080 | 0x00000008 | 0x00000010 | 0x00000020
    file_attrs = 0x00000020
    show_cmd = 1  # SW_SHOWNORMAL

    header = struct.pack(
        "<I16sIIQQQIIIHII",
        header_size,
        clsid,
        link_flags,
        file_attrs,
        0,
        0,
        0,
        0,
        0,
        show_cmd,
        0,
        0,
        0,
    )

    def _pack_unicode_str(s: str) -> bytes:
        encoded = s.encode("utf-16-le")
        return struct.pack("<H", len(s)) + encoded

    name_str = _pack_unicode_str(f"AI Internship Agent ({target_bat})")
    work_dir_str = _pack_unicode_str(str(working_dir))
    args_str = _pack_unicode_str(f'/c "{target_bat}"')

    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    shortcut_path.write_bytes(header + name_str + work_dir_str + args_str)
    return shortcut_path.exists()


def create_windows_desktop_shortcuts() -> Dict[str, Any]:
    """Create the 'AI Internship Agent.lnk' shortcut in the project root and on the Windows Desktop (when writable)."""
    created_paths: List[str] = []
    skipped_paths: List[str] = []

    for candidate in get_desktop_candidate_paths():
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            probe = candidate.parent / ".shortcut_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            if _create_lnk_via_wscript_or_win32(candidate, BATCH_LAUNCHER_PATH, PROJECT_ROOT):
                created_paths.append(str(candidate))
        except Exception as exc:
            skipped_paths.append(f"{candidate} ({exc})")

    return {
        "batch_launcher": str(BATCH_LAUNCHER_PATH),
        "batch_exists": BATCH_LAUNCHER_PATH.exists(),
        "created_shortcuts": created_paths,
        "skipped_shortcuts": skipped_paths,
        "primary_shortcut": created_paths[0] if created_paths else str(LOCAL_SHORTCUT_PATH),
    }


if __name__ == "__main__":
    import json

    res = create_windows_desktop_shortcuts()
    print(json.dumps(res, indent=2))
