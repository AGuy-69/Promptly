# -*- mode: python ; coding: utf-8 -*-
# PromptlyAI — macOS .app build spec
#
# Build command:
#   pyinstaller promptly_ai_mac.spec
#
# Output: dist/PromptlyAI.app

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

_ctk_all = collect_data_files("customtkinter")
ctk_datas = [
    (src, dst) for src, dst in _ctk_all
    if os.path.basename(src) not in ("blue.json", "green.json")
]

groq_datas     = collect_data_files("groq")
httpx_datas    = collect_data_files("httpx")
httpcore_datas = collect_data_files("httpcore")
keyboard_datas = collect_data_files("keyboard")

all_datas = (
    ctk_datas
    + groq_datas
    + httpx_datas
    + httpcore_datas
    + keyboard_datas
)

hidden = [
    *collect_submodules("customtkinter"),
    "httpx",
    "httpcore",
    "httpcore._async",
    "httpcore._sync",
    "anyio",
    "anyio._backends._asyncio",
    "anyio._backends._trio",
    "sniffio",
    "pkg_resources",
    "pkg_resources.extern",
    "jaraco",
    "jaraco.text",
    "jaraco.context",
    "jaraco.functools",
    "more_itertools",
    "importlib_resources",
    "importlib_metadata",
    "zipp",
    "tkinter",
    "tkinter.ttk",
    "tkinter.font",
    "tkinter.colorchooser",
    "pyperclip",
    "pyperclip.handlers",
    "keyboard",
    "_thread",
    "ctypes",
    # macOS uses AppKit instead of wintypes
    "AppKit",
    "ssl",
    "certifi",
]

a = Analysis(
    ["Promptly-Mac.py"],
    pathex=[os.path.abspath(".")],
    binaries=[],
    datas=all_datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "numpy", "pandas", "matplotlib", "scipy",
        "PIL", "Pillow",
        "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
        "IPython", "jupyter", "notebook", "pytest",
        "lxml", "xmlrpc", "Cython", "tzdata",
        "pydoc", "doctest", "unittest", "lib2to3",
        "multiprocessing", "test", "tkinter.test",
        # Windows-only — exclude on macOS
        "ctypes.wintypes",
        "winreg",
        "win32api",
        "win32con",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

def _should_drop(dest_path: str) -> bool:
    p = dest_path.replace("\\", "/")
    drop_patterns = [
        "_tk_data/images/",
        "_tk_data/msgs/cs.msg", "_tk_data/msgs/da.msg",
        "_tk_data/msgs/de.msg", "_tk_data/msgs/el.msg",
        "_tk_data/msgs/en_gb.msg", "_tk_data/msgs/eo.msg",
        "_tk_data/msgs/es.msg", "_tk_data/msgs/fi.msg",
        "_tk_data/msgs/fr.msg", "_tk_data/msgs/hu.msg",
        "_tk_data/msgs/it.msg", "_tk_data/msgs/nl.msg",
        "_tk_data/msgs/pl.msg", "_tk_data/msgs/pt.msg",
        "_tk_data/msgs/ru.msg", "_tk_data/msgs/sv.msg",
        "_tk_data/msgs/zh_cn.msg",
        "lxml/", "Cython/", "tzdata/",
        # Keep aquaTheme on macOS — Tk needs it
    ]
    return any(pat in p for pat in drop_patterns)

a.datas = [(dest, src, kind)
           for dest, src, kind in a.datas
           if not _should_drop(dest)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PromptlyAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        # macOS equivalents — no .dll/.pyd
        "Python",
        "libpython*.dylib",
        "libtk*.dylib",
        "libtcl*.dylib",
    ],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,       # ← macOS: handles open-file Apple Events
    target_arch=None,          # None = native; set "universal2" for M1+Intel fat binary
    codesign_identity=None,    # set to your Apple Developer ID to sign
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[
        "Python",
        "libpython*.dylib",
        "libtk*.dylib",
        "libtcl*.dylib",
    ],
    name="PromptlyAI",
)

# ── BUNDLE — this is what makes it a .app ────────────────────────────────────
app = BUNDLE(
    coll,
    name="PromptlyAI.app",
    bundle_identifier="com.yourname.promptlyai",   # ← change this
    info_plist={
        "CFBundleName": "PromptlyAI",
        "CFBundleDisplayName": "PromptlyAI",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,            # Retina support
        "NSRequiresAquaSystemAppearance": False,    # allows dark mode
        "LSMinimumSystemVersion": "11.0",           # macOS Big Sur+
    },
)