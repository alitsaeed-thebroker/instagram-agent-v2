"""One encoding-safe console boundary for Windows and Unicode project names."""
from __future__ import annotations
import sys
from typing import TextIO

MOJIBAKE_MARKERS=("Ã","Â","â€","â€”")

def configure_utf8_console(stdout:TextIO|None=None,stderr:TextIO|None=None)->None:
    for stream in (stdout or sys.stdout,stderr or sys.stderr):
        reconfigure=getattr(stream,"reconfigure",None)
        if callable(reconfigure):
            try:reconfigure(encoding="utf-8",errors="backslashreplace")
            except (OSError,ValueError):pass

def has_mojibake(value:str)->bool:return any(marker in value for marker in MOJIBAKE_MARKERS)
