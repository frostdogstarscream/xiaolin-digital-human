"""Process-local CRT loading for a venv based on older Conda Python on Windows."""
import os
from pathlib import Path

_handles=[]


def prepare_runtime():
    if os.name=='nt' and not _handles:
        import ctypes
        system=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32'
        # Conda's application directory contains older copies. Explicitly load the
        # already-installed system runtime before torch; do not replace any DLL.
        for name in ['msvcp140.dll','vcruntime140_1.dll']:
            path=system/name
            if path.is_file():_handles.append(ctypes.WinDLL(str(path)))
    os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY','1')
    os.environ.setdefault('TOKENIZERS_PARALLELISM','false')
