"""
PromptlyAI — Desktop AI assistant (macOS + Windows compatible)
Hotkey: Ctrl+Shift+F  →  grabs selection, sends to Llama, copies answer
Stealth Mode toggle: hides the window while still intercepting the hotkey
APIs Tab: save multiple Groq API keys with auto-failover
"""

import threading
import time
import queue
import json
import os
import sys
import platform
import pyperclip
import customtkinter as ctk
import tkinter as tk
from groq import Groq

# ── Platform detection ───────────────────────────────────────────────────────
IS_MAC     = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"

# ── Hotkey backend: pynput on macOS, keyboard on Windows ────────────────────
if IS_MAC:
    from pynput import keyboard as pynput_kb
    from pynput.keyboard import Key, KeyCode, Controller as KeyController
    _kb_controller = KeyController()
else:
    import keyboard

# ── Config ──────────────────────────────────────────────────────────────────
MODEL          = "llama-3.3-70b-versatile"
# Use Cmd on macOS, Ctrl on Windows
MOD_KEY        = "<cmd>" if IS_MAC else "ctrl"
HOTKEY         = f"{MOD_KEY}+shift+f"
HOTKEY_STEALTH = f"{MOD_KEY}+shift+h"
KEYS_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "promptly_keys.json")
# ────────────────────────────────────────────────────────────────────────────

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

BLUE_D   = "#3B82F6"
BLUE_D_D = "#2F6CCD"
BG_DEEP  = "#151515"
BG_CARD  = "#121212"
BG_INPUT = "#1A1A1A"
TEXT_PRI = "#FFFFFF"
TEXT_MUT = "#666666"
TEXT_DIM = "#4A4A4A"
BORDER   = "#222222"
GREEN    = "#3DBA74"
RED      = "#EF4444"
AMBER    = "#E8900A"


# ── Key storage helpers ──────────────────────────────────────────────────────

def load_keys() -> list[dict]:
    try:
        if os.path.exists(KEYS_FILE):
            with open(KEYS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []


def save_keys(keys: list[dict]):
    try:
        with open(KEYS_FILE, "w", encoding="utf-8") as f:
            json.dump(keys, f, indent=2)
    except Exception as e:
        print(f"Failed to save keys: {e}")


# ── macOS hotkey listener ────────────────────────────────────────────────────

class MacHotkeyListener:
    """
    Listens for Cmd+Shift+F and Cmd+Shift+H on macOS using pynput.
    Callbacks are fired on the listener thread; callers must marshal to main thread.
    NOTE: macOS requires Accessibility permissions for global hotkeys.
    System Preferences → Privacy & Security → Accessibility → grant Terminal / your app.
    """
    def __init__(self, on_ask, on_stealth):
        self._on_ask     = on_ask
        self._on_stealth = on_stealth
        self._pressed    = set()
        self._listener   = None

    def start(self):
        self._listener = pynput_kb.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()

    def _canonical(self, key):
        """Normalise key to a comparable value."""
        try:
            return key.char.lower() if hasattr(key, "char") and key.char else key
        except Exception:
            return key

    def _on_press(self, key):
        self._pressed.add(self._canonical(key))
        mods = {Key.cmd, Key.cmd_l, Key.cmd_r}
        has_cmd   = any(k in self._pressed for k in mods)
        has_shift = Key.shift in self._pressed or Key.shift_l in self._pressed or Key.shift_r in self._pressed
        has_f     = "f" in self._pressed
        has_h     = "h" in self._pressed

        if has_cmd and has_shift and has_f:
            self._on_ask()
        elif has_cmd and has_shift and has_h:
            self._on_stealth()

    def _on_release(self, key):
        self._pressed.discard(self._canonical(key))


# ── Main App ─────────────────────────────────────────────────────────────────

class PromptlyAI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.api_keys      = load_keys()
        self._active_idx   = 0
        self._build_client()

        self.history     = []
        self.query_count = 0
        self.stealth     = False
        self.loading     = False
        self._task_q     = queue.Queue()
        self._mac_listener = None

        # macOS: set icon via iconphoto (accepts .png/.gif, not .ico)
        if IS_MAC:
            try:
                icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "PromptlyAI.png")
                if os.path.exists(icon_path):
                    icon_img = tk.PhotoImage(file=icon_path)
                    self.iconphoto(True, icon_img)
            except Exception:
                pass
        else:
            try:
                self.iconbitmap("RJ8BVML.ico")
            except Exception:
                pass

        self._build_window()
        self._build_ui()
        self._bind_hotkey()
        self._poll_queue()

    # ── Client management ────────────────────────────────────────────────────

    def _build_client(self):
        active = [k for k in self.api_keys if k.get("active", True)]
        if active and self._active_idx < len(active):
            try:
                self.client = Groq(api_key=active[self._active_idx]["key"])
            except Exception:
                self.client = None
        else:
            self.client = None

    def _active_keys(self) -> list[dict]:
        return [k for k in self.api_keys if k.get("active", True)]

    def _rotate_key(self) -> bool:
        active = self._active_keys()
        if len(active) <= 1:
            return False
        self._active_idx = (self._active_idx + 1) % len(active)
        try:
            self.client = Groq(api_key=active[self._active_idx]["key"])
            return True
        except Exception:
            return False

    # ── Window ───────────────────────────────────────────────────────────────

    def _build_window(self):
        self.title("PromptlyAI")
        self.geometry("560x680")
        self.minsize(480, 600)
        self.configure(fg_color=BG_DEEP)
        self.resizable(True, True)
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x  = (sw - 560) // 2
        y  = (sh - 680) // 2
        self.geometry(f"560x680+{x}+{y}")

    # ── UI (unchanged from original) ─────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        self._build_tabs()
        self._build_tab_ask()
        self._build_tab_history()
        self._build_tab_apis()
        self._build_footer()
        self._show_tab("ask")

    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=52,
                           border_width=0)
        hdr.pack(fill="x", side="top")
        hdr.pack_propagate(False)

        inner = ctk.CTkFrame(hdr, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20, pady=0)

        logo = ctk.CTkLabel(inner, text="Promptly", font=("Arial Black", 18, "bold"),
                             text_color=TEXT_PRI)
        logo.pack(side="left", pady=14)
        logo_acc = ctk.CTkLabel(inner, text="AI", font=("Arial Black", 18, "bold"),
                                text_color=BLUE_D)
        logo_acc.pack(side="left", pady=14)

        self.status_frame = ctk.CTkFrame(inner, fg_color="transparent")
        self.status_frame.pack(side="right", pady=14)

        self.dot_canvas = tk.Canvas(self.status_frame, width=10, height=10,
                                    bg=BG_CARD, highlightthickness=0)
        self.dot_canvas.pack(side="left", padx=(0, 5))
        self._draw_dot(GREEN)

        self.status_lbl = ctk.CTkLabel(self.status_frame, text="Listening",
                                        font=("Arial", 12), text_color=TEXT_MUT)
        self.status_lbl.pack(side="left")

        # Show platform-appropriate hotkey hint
        hotkey_display = "⌘+SHIFT+F" if IS_MAC else "CTRL+SHIFT+F"
        badge = ctk.CTkFrame(inner, fg_color="#1E1E1E", corner_radius=6,
                              border_width=1, border_color=BORDER)
        badge.pack(side="right", padx=(0, 14), pady=16)
        ctk.CTkLabel(badge, text=hotkey_display, font=("Courier", 10, "bold"),
                     text_color=TEXT_MUT).pack(padx=8, pady=3)

    def _draw_dot(self, color):
        self.dot_canvas.delete("all")
        self.dot_canvas.create_oval(1, 1, 9, 9, fill=color, outline="")

    def _build_tabs(self):
        tab_row = ctk.CTkFrame(self, fg_color=BG_DEEP, height=40)
        tab_row.pack(fill="x", padx=20, pady=(14, 0))
        tab_row.pack_propagate(False)

        self.tab_ask_btn  = self._tab_btn(tab_row, "Ask",     lambda: self._show_tab("ask"))
        self.tab_ask_btn.pack(side="left")
        self.tab_hist_btn = self._tab_btn(tab_row, "History", lambda: self._show_tab("history"))
        self.tab_hist_btn.pack(side="left", padx=(6, 0))
        self.tab_api_btn  = self._tab_btn(tab_row, "APIs",    lambda: self._show_tab("apis"))
        self.tab_api_btn.pack(side="left", padx=(6, 0))

    def _tab_btn(self, parent, text, cmd):
        return ctk.CTkButton(parent, text=text, width=80, height=32,
                             corner_radius=16, fg_color="transparent",
                             hover_color="#1C1C1C", text_color=TEXT_MUT,
                             font=("Arial", 13), command=cmd, border_width=0)

    def _show_tab(self, tab):
        self.current_tab = tab
        all_btns   = [self.tab_ask_btn, self.tab_hist_btn, self.tab_api_btn]
        all_frames = [self.ask_frame, self.hist_frame, self.api_frame]

        for btn in all_btns:
            btn.configure(fg_color="transparent", text_color=TEXT_MUT, hover_color="#1C1C1C")
        for frame in all_frames:
            frame.pack_forget()

        if tab == "ask":
            self.tab_ask_btn.configure(fg_color=BLUE_D, text_color="#FFFFFF", hover_color=BLUE_D_D)
            self.ask_frame.pack(fill="both", expand=True, padx=20, pady=(10, 0))
        elif tab == "history":
            self.tab_hist_btn.configure(fg_color=BLUE_D, text_color="#FFFFFF", hover_color=BLUE_D_D)
            self.hist_frame.pack(fill="both", expand=True, padx=20, pady=(10, 0))
            self._render_history()
        elif tab == "apis":
            self.tab_api_btn.configure(fg_color=BLUE_D, text_color="#FFFFFF", hover_color=BLUE_D_D)
            self.api_frame.pack(fill="both", expand=True, padx=20, pady=(10, 0))
            self._render_api_list()

    def _build_tab_ask(self):
        self.ask_frame = ctk.CTkFrame(self, fg_color="transparent")

        ctk.CTkLabel(self.ask_frame,
                     text="Highlight text anywhere, press the hotkey, get instant AI answers",
                     font=("Arial", 12), text_color=TEXT_MUT,
                     wraplength=500, justify="left").pack(anchor="w", pady=(0, 12))

        ctk.CTkLabel(self.ask_frame, text="INPUT", font=("Arial", 10, "bold"),
                     text_color=TEXT_DIM).pack(anchor="w", pady=(0, 4))

        self.input_box = ctk.CTkTextbox(
            self.ask_frame, height=110, corner_radius=10,
            fg_color=BG_INPUT, border_color=BORDER, border_width=1,
            font=("Arial", 13), text_color=TEXT_PRI,
            scrollbar_button_color=BORDER, wrap="word"
        )
        self.input_box.pack(fill="x", pady=(0, 10))
        self.input_box.insert("0.0", "Paste or type text here…")
        self.input_box.configure(text_color=TEXT_MUT)
        self.input_box.bind("<FocusIn>",  self._on_input_focus)
        self.input_box.bind("<FocusOut>", self._on_input_blur)
        self._input_is_placeholder = True

        btn_row = ctk.CTkFrame(self.ask_frame, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 12))

        self.ask_btn = ctk.CTkButton(
            btn_row, text="✦  Ask Llama", height=38, corner_radius=10,
            fg_color=BLUE_D, hover_color=BLUE_D_D, text_color="#FFFFFF",
            font=("Arial", 13, "bold"), command=self._ask_from_box
        )
        self.ask_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            btn_row, text="Clear", width=70, height=38, corner_radius=10,
            fg_color="#1C1C1C", hover_color="#252525", text_color=TEXT_MUT,
            font=("Arial", 13), border_width=1, border_color=BORDER,
            command=self._clear_all
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row, text="⎘", width=38, height=38, corner_radius=10,
            fg_color="#1C1C1C", hover_color="#252525", text_color=TEXT_MUT,
            font=("Arial", 16), border_width=1, border_color=BORDER,
            command=self._paste_clipboard
        ).pack(side="left")

        out_lbl_row = ctk.CTkFrame(self.ask_frame, fg_color="transparent")
        out_lbl_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(out_lbl_row, text="RESPONSE", font=("Arial", 10, "bold"),
                     text_color=TEXT_DIM).pack(side="left")
        self.copy_btn = ctk.CTkButton(
            out_lbl_row, text="Copy", width=50, height=22, corner_radius=6,
            fg_color="transparent", hover_color="#1C1C1C", text_color=TEXT_MUT,
            font=("Arial", 11), border_width=1, border_color=BORDER,
            command=self._copy_output
        )
        self.copy_btn.pack(side="right")

        self.output_box = ctk.CTkTextbox(
            self.ask_frame, height=180, corner_radius=10,
            fg_color=BG_INPUT, border_color=BORDER, border_width=1,
            font=("Arial", 13), text_color=TEXT_MUT,
            scrollbar_button_color=BORDER, wrap="word", state="disabled"
        )
        self.output_box.pack(fill="both", expand=True)

        stealth_row = ctk.CTkFrame(self.ask_frame, fg_color="transparent")
        stealth_row.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(stealth_row, text="Stealth Mode",
                     font=("Arial", 12), text_color=TEXT_MUT).pack(side="left")
        ctk.CTkLabel(stealth_row,
                     text="Hide window — hotkey still works in background",
                     font=("Arial", 11), text_color=TEXT_DIM).pack(side="left", padx=(6, 0))
        self.stealth_switch = ctk.CTkSwitch(
            stealth_row, text="", width=40,
            progress_color=BLUE_D, button_color="#DDDDDD",
            fg_color="#2A2A2A", command=self._toggle_stealth
        )
        self.stealth_switch.pack(side="right")

    def _build_tab_history(self):
        self.hist_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.hist_scroll = ctk.CTkScrollableFrame(
            self.hist_frame, fg_color="transparent",
            scrollbar_button_color=BORDER
        )
        self.hist_scroll.pack(fill="both", expand=True)

    def _render_history(self):
        for w in self.hist_scroll.winfo_children():
            w.destroy()
        if not self.history:
            ctk.CTkLabel(self.hist_scroll, text="No history yet",
                         font=("Arial", 13), text_color=TEXT_DIM).pack(pady=30)
            return
        for i, (q, a, ts) in enumerate(reversed(self.history)):
            card = ctk.CTkFrame(self.hist_scroll, fg_color=BG_CARD, corner_radius=10,
                                border_width=1, border_color=BORDER)
            card.pack(fill="x", pady=(0, 8))
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(10, 4))
            ctk.CTkLabel(top, text=ts, font=("Arial", 10), text_color=TEXT_DIM).pack(side="right")
            q_preview = q[:120] + ("…" if len(q) > 120 else "")
            ctk.CTkLabel(card, text=q_preview, font=("Arial", 12), text_color=TEXT_MUT,
                         wraplength=460, justify="left").pack(anchor="w", padx=12, pady=(0, 6))
            sep = ctk.CTkFrame(card, fg_color=BORDER, height=1)
            sep.pack(fill="x", padx=12)
            a_preview = a[:120] + ("…" if len(a) > 120 else "")
            ctk.CTkLabel(card, text=a_preview, font=("Arial", 12), text_color=TEXT_MUT,
                         wraplength=460, justify="left").pack(anchor="w", padx=12, pady=(6, 6))
            idx = len(self.history) - 1 - i
            ctk.CTkButton(
                card, text="Load →", height=26, width=70, corner_radius=6,
                fg_color="transparent", hover_color="#1C1C1C", text_color=BLUE_D,
                font=("Arial", 11), border_width=1, border_color=BORDER,
                command=lambda ix=idx: self._load_history(ix)
            ).pack(anchor="e", padx=12, pady=(0, 10))

    def _build_tab_apis(self):
        self.api_frame = ctk.CTkFrame(self, fg_color="transparent")

        ctk.CTkLabel(
            self.api_frame,
            text="Add multiple Groq API keys. If one fails, the next active key is used automatically.",
            font=("Arial", 12), text_color=TEXT_MUT,
            wraplength=500, justify="left"
        ).pack(anchor="w", pady=(0, 12))

        form = ctk.CTkFrame(self.api_frame, fg_color=BG_CARD, corner_radius=10,
                            border_width=1, border_color=BORDER)
        form.pack(fill="x", pady=(0, 12))
        form_inner = ctk.CTkFrame(form, fg_color="transparent")
        form_inner.pack(fill="x", padx=14, pady=12)

        lbl_row = ctk.CTkFrame(form_inner, fg_color="transparent")
        lbl_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(lbl_row, text="LABEL", font=("Arial", 10, "bold"),
                     text_color=TEXT_DIM).pack(side="left")

        self.api_label_entry = ctk.CTkEntry(
            form_inner, placeholder_text="e.g. Key 1 / Work / Backup",
            height=34, corner_radius=8,
            fg_color=BG_INPUT, border_color=BORDER, border_width=1,
            font=("Arial", 12), text_color=TEXT_PRI
        )
        self.api_label_entry.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(form_inner, text="API KEY", font=("Arial", 10, "bold"),
                     text_color=TEXT_DIM).pack(anchor="w", pady=(0, 4))

        key_row = ctk.CTkFrame(form_inner, fg_color="transparent")
        key_row.pack(fill="x", pady=(0, 8))

        self.api_key_entry = ctk.CTkEntry(
            key_row, placeholder_text="gsk_…",
            height=34, corner_radius=8, show="•",
            fg_color=BG_INPUT, border_color=BORDER, border_width=1,
            font=("Arial", 12), text_color=TEXT_PRI
        )
        self.api_key_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.show_key_var = tk.BooleanVar(value=False)
        ctk.CTkButton(
            key_row, text="👁", width=34, height=34, corner_radius=8,
            fg_color="#1C1C1C", hover_color="#252525", text_color=TEXT_MUT,
            font=("Arial", 14), border_width=1, border_color=BORDER,
            command=self._toggle_key_visibility
        ).pack(side="left")

        ctk.CTkButton(
            form_inner, text="＋  Add Key", height=36, corner_radius=8,
            fg_color=BLUE_D, hover_color=BLUE_D_D, text_color="#FFFFFF",
            font=("Arial", 13, "bold"), command=self._add_api_key
        ).pack(fill="x")

        ctk.CTkLabel(self.api_frame, text="SAVED KEYS", font=("Arial", 10, "bold"),
                     text_color=TEXT_DIM).pack(anchor="w", pady=(4, 6))

        self.api_list_frame = ctk.CTkScrollableFrame(
            self.api_frame, fg_color="transparent",
            scrollbar_button_color=BORDER, height=220
        )
        self.api_list_frame.pack(fill="both", expand=True)

    def _toggle_key_visibility(self):
        current = self.api_key_entry.cget("show")
        self.api_key_entry.configure(show="" if current == "•" else "•")

    def _add_api_key(self):
        label = self.api_label_entry.get().strip()
        key   = self.api_key_entry.get().strip()
        if not key:
            self._toast("Enter an API key first")
            return
        if not label:
            label = f"Key {len(self.api_keys) + 1}"
        if any(k["key"] == key for k in self.api_keys):
            self._toast("That key is already saved")
            return
        self.api_keys.append({"label": label, "key": key, "active": True})
        save_keys(self.api_keys)
        if len(self._active_keys()) == 1:
            self._active_idx = 0
            self._build_client()
        self.api_label_entry.delete(0, "end")
        self.api_key_entry.delete(0, "end")
        self._render_api_list()
        self._update_footer_key_count()
        self._toast(f'"{label}" saved ✓')

    def _render_api_list(self):
        for w in self.api_list_frame.winfo_children():
            w.destroy()
        if not self.api_keys:
            ctk.CTkLabel(self.api_list_frame,
                         text="No API keys yet — add one above",
                         font=("Arial", 13), text_color=TEXT_DIM).pack(pady=20)
            return
        active_keys  = self._active_keys()
        current_key  = active_keys[self._active_idx]["key"] if active_keys else None
        for i, kd in enumerate(self.api_keys):
            is_current = kd.get("active", True) and kd["key"] == current_key
            card = ctk.CTkFrame(
                self.api_list_frame, fg_color=BG_CARD, corner_radius=10,
                border_width=1, border_color=BLUE_D if is_current else BORDER
            )
            card.pack(fill="x", pady=(0, 8))
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=10)
            dot_c = tk.Canvas(row, width=10, height=10, bg=BG_CARD, highlightthickness=0)
            dot_c.pack(side="left", padx=(0, 8))
            dot_color = BLUE_D if is_current else (GREEN if kd.get("active", True) else TEXT_DIM)
            dot_c.create_oval(1, 1, 9, 9, fill=dot_color, outline="")
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(info, text=kd["label"], font=("Arial", 13, "bold"),
                         text_color=TEXT_PRI if kd.get("active", True) else TEXT_DIM,
                         anchor="w").pack(anchor="w")
            masked = kd["key"][:8] + "••••••••" + kd["key"][-4:]
            status_text = "  ← IN USE" if is_current else ""
            ctk.CTkLabel(info, text=masked + status_text,
                         font=("Courier", 10), text_color=BLUE_D if is_current else TEXT_MUT,
                         anchor="w").pack(anchor="w")
            btn_col = ctk.CTkFrame(row, fg_color="transparent")
            btn_col.pack(side="right")
            toggle_text = "Disable" if kd.get("active", True) else "Enable"
            ctk.CTkButton(
                btn_col, text=toggle_text, width=62, height=26, corner_radius=6,
                fg_color="transparent", hover_color="#1C1C1C",
                text_color=AMBER if kd.get("active", True) else GREEN,
                font=("Arial", 11), border_width=1, border_color=BORDER,
                command=lambda ix=i: self._toggle_key_active(ix)
            ).pack(side="left", padx=(0, 6))
            ctk.CTkButton(
                btn_col, text="✕", width=28, height=26, corner_radius=6,
                fg_color="transparent", hover_color="#2A0A0A",
                text_color=RED, font=("Arial", 12), border_width=1,
                border_color="#3A1A1A",
                command=lambda ix=i: self._delete_api_key(ix)
            ).pack(side="left")

    def _toggle_key_active(self, idx: int):
        self.api_keys[idx]["active"] = not self.api_keys[idx].get("active", True)
        save_keys(self.api_keys)
        active = self._active_keys()
        if active:
            self._active_idx = min(self._active_idx, len(active) - 1)
            self._build_client()
        else:
            self.client = None
        self._render_api_list()
        self._update_footer_key_count()

    def _delete_api_key(self, idx: int):
        self.api_keys.pop(idx)
        save_keys(self.api_keys)
        active = self._active_keys()
        if active:
            self._active_idx = min(self._active_idx, len(active) - 1)
            self._build_client()
        else:
            self._active_idx = 0
            self.client = None
        self._render_api_list()
        self._update_footer_key_count()

    def _build_footer(self):
        foot = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=40,
                            border_width=0)
        foot.pack(fill="x", side="bottom")
        foot.pack_propagate(False)
        inner = ctk.CTkFrame(foot, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20)
        model_pill = ctk.CTkFrame(inner, fg_color="#0B0D13", corner_radius=20,
                                   border_width=1, border_color="#061831")
        model_pill.pack(side="left", pady=8)
        ctk.CTkLabel(model_pill, text=f"⚡ {MODEL}", font=("Arial", 10),
                     text_color=BLUE_D).pack(padx=10, pady=3)
        self.count_lbl = ctk.CTkLabel(inner, text="0 queries this session",
                                       font=("Arial", 11), text_color=TEXT_DIM)
        self.count_lbl.pack(side="right", pady=8)
        self.key_count_lbl = ctk.CTkLabel(inner, text="",
                                           font=("Arial", 11), text_color=TEXT_DIM)
        self.key_count_lbl.pack(side="right", padx=(0, 14), pady=8)
        self._update_footer_key_count()

    def _update_footer_key_count(self):
        total  = len(self.api_keys)
        active = len(self._active_keys())
        if hasattr(self, "key_count_lbl"):
            if total == 0:
                self.key_count_lbl.configure(text="No keys saved")
            else:
                self.key_count_lbl.configure(text=f"{active}/{total} keys active")

    # ── Hotkey & Stealth ──────────────────────────────────────────────────────

    def _emergency_unhide(self):
        if self.stealth:
            self.stealth_switch.deselect()
            self.stealth = False
            self.deiconify()
            self.lift()
            self.focus_force()

    def _bind_hotkey(self):
        if IS_MAC:
            # pynput listener — fires callbacks on its own thread
            self._mac_listener = MacHotkeyListener(
                on_ask=lambda: threading.Thread(target=self._on_hotkey, daemon=True).start(),
                on_stealth=lambda: self.after(0, self._emergency_unhide)
            )
            self._mac_listener.start()
        else:
            try:
                keyboard.add_hotkey(HOTKEY, lambda: threading.Thread(
                    target=self._on_hotkey, daemon=True).start())
                keyboard.add_hotkey(HOTKEY_STEALTH, lambda: self.after(0, self._emergency_unhide))
            except Exception as e:
                print(f"Error registering global hotkey: {e}")

    def _on_hotkey(self):
        if self.loading:
            return
        self.after(0, lambda: self._show_status(BLUE_D, "Capturing…"))
        try:
            pyperclip.copy("")
        except Exception:
            pass
        time.sleep(0.3)

        # Send Cmd+C on macOS, Ctrl+C on Windows
        if IS_MAC:
            _kb_controller.press(Key.cmd)
            _kb_controller.press("c")
            _kb_controller.release("c")
            _kb_controller.release(Key.cmd)
        else:
            keyboard.send("ctrl+c")

        time.sleep(0.1)
        self.after(0, self._grab_and_ask)

    def _grab_and_ask(self):
        try:
            text = pyperclip.paste()
        except Exception:
            text = ""
        if not text or not text.strip():
            self.after(100, self._fallback_grab)
            return
        self._set_input(text)
        self._submit_query(text)

    def _fallback_grab(self):
        text = pyperclip.paste()
        if not text or not text.strip():
            self._show_status(GREEN, "Nothing selected")
            self._toast("Copy failed — highlight text first")
            return
        self._set_input(text)
        self._submit_query(text)

    def _toggle_stealth(self):
        self.stealth = self.stealth_switch.get()
        if self.stealth:
            self.withdraw()
            self._show_tray_info()
        else:
            self.deiconify()
            self.lift()
            self.focus_force()

    def _show_tray_info(self):
        tip = ctk.CTkToplevel(self)
        tip.title("")
        tip.geometry("300x100")
        tip.configure(fg_color=BG_CARD)
        tip.attributes("-topmost", True)
        tip.resizable(False, False)
        sw = self.winfo_screenwidth()
        tip.geometry(f"300x100+{sw-320}+40")
        hotkey_display = "⌘+Shift+H" if IS_MAC else "Ctrl+Shift+H"
        ctk.CTkLabel(tip, text="👁  Stealth Mode Active",
                     font=("Arial", 13, "bold"), text_color=BLUE_D).pack(pady=(18, 4))
        ctk.CTkLabel(tip, text=f"Hotkey still works. Press {hotkey_display} to return",
                     font=("Arial", 11), text_color=TEXT_MUT).pack()
        tip.after(3000, tip.destroy)

    # ── Query flow ────────────────────────────────────────────────────────────

    def _ask_from_box(self):
        if self.loading:
            return
        text = self._get_input()
        if not text:
            self._toast("Nothing to send")
            return
        self._submit_query(text)

    def _submit_query(self, text):
        if not self._active_keys():
            self._toast("No active API keys — add one in the APIs tab")
            self._show_status(RED, "No API key")
            return
        self.loading = True
        self._set_loading(True)
        self._show_status(AMBER, "Thinking…")
        threading.Thread(target=self._worker, args=(text,), daemon=True).start()

    def _worker(self, text):
        active = self._active_keys()
        if not active:
            self._task_q.put(("result", text, "Error: No active API keys saved."))
            return
        attempts   = len(active)
        last_error = "Unknown error"
        for attempt in range(attempts):
            try:
                if self.client is None:
                    raise RuntimeError("No Groq client initialised")
                resp = self.client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": text}]
                )
                answer = resp.choices[0].message.content
                self._task_q.put(("result", text, answer))
                return
            except Exception as e:
                last_error = str(e)
                if attempt < attempts - 1:
                    rotated = self._rotate_key()
                    if not rotated:
                        break
                    active_now = self._active_keys()
                    new_label  = active_now[self._active_idx]["label"] if active_now else "?"
                    self.after(0, lambda lbl=new_label: self._show_status(
                        AMBER, f"Switched to {lbl}…"))
                    time.sleep(0.5)
        self._task_q.put(("result", text, f"Error: All API keys failed. Last error: {last_error}"))

    def _poll_queue(self):
        try:
            while True:
                item = self._task_q.get_nowait()
                if item[0] == "result":
                    _, q, a = item
                    self._on_result(q, a)
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    def _on_result(self, q, a):
        self.loading = False
        self._set_loading(False)
        self._show_output(a)
        pyperclip.copy(a)
        ts = time.strftime("%H:%M:%S")
        self.history.append((q, a, ts))
        self.query_count += 1
        self.count_lbl.configure(
            text=f"{self.query_count} quer{'y' if self.query_count == 1 else 'ies'} this session")
        self._show_status(GREEN, "Done — answer copied!")
        self.after(3000, lambda: self._show_status(GREEN, "Listening"))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _on_input_focus(self, e):
        if self._input_is_placeholder:
            self.input_box.delete("0.0", "end")
            self.input_box.configure(text_color=TEXT_PRI)
            self._input_is_placeholder = False

    def _on_input_blur(self, e):
        if not self.input_box.get("0.0", "end").strip():
            self.input_box.insert("0.0", "Paste or type text here…")
            self.input_box.configure(text_color=TEXT_MUT)
            self._input_is_placeholder = True

    def _get_input(self):
        if self._input_is_placeholder:
            return ""
        return self.input_box.get("0.0", "end").strip()

    def _set_input(self, text):
        if self._input_is_placeholder:
            self.input_box.delete("0.0", "end")
            self.input_box.configure(text_color=TEXT_PRI)
            self._input_is_placeholder = False
        else:
            self.input_box.delete("0.0", "end")
        self.input_box.insert("0.0", text)

    def _show_output(self, text):
        self.output_box.configure(state="normal", text_color=TEXT_PRI)
        self.output_box.delete("0.0", "end")
        self.output_box.insert("0.0", text)
        self.output_box.configure(state="disabled")

    def _set_loading(self, on):
        if on:
            self.ask_btn.configure(text="⏳  Thinking…", state="disabled", fg_color="#061831")
        else:
            self.ask_btn.configure(text="✦  Ask Llama", state="normal", fg_color=BLUE_D)

    def _show_status(self, color, text):
        self._draw_dot(color)
        self.status_lbl.configure(text=text)

    def _paste_clipboard(self):
        try:
            text = pyperclip.paste()
            if text:
                self._set_input(text)
        except Exception:
            self._toast("Clipboard read failed")

    def _clear_all(self):
        self.input_box.delete("0.0", "end")
        self.input_box.insert("0.0", "Paste or type text here…")
        self.input_box.configure(text_color=TEXT_MUT)
        self._input_is_placeholder = True
        self.output_box.configure(state="normal")
        self.output_box.delete("0.0", "end")
        self.output_box.configure(state="disabled", text_color=TEXT_MUT)

    def _copy_output(self):
        self.output_box.configure(state="normal")
        text = self.output_box.get("0.0", "end").strip()
        self.output_box.configure(state="disabled")
        if text:
            pyperclip.copy(text)
            self.copy_btn.configure(text="✓ Copied", text_color=GREEN)
            self.after(1800, lambda: self.copy_btn.configure(text="Copy", text_color=TEXT_MUT))

    def _load_history(self, idx):
        q, a, _ = self.history[idx]
        self._show_tab("ask")
        self._set_input(q)
        self._show_output(a)

    def _toast(self, msg):
        old = self.status_lbl.cget("text")
        self.status_lbl.configure(text=msg, text_color=BLUE_D)
        self.after(2500, lambda: self.status_lbl.configure(text=old, text_color=TEXT_MUT))

    def destroy(self):
        if IS_MAC and self._mac_listener:
            self._mac_listener.stop()
        elif IS_WINDOWS:
            keyboard.unhook_all()
        super().destroy()


if __name__ == "__main__":
    print("PromptlyAI starting…")
    app = PromptlyAI()
    app.protocol("WM_DELETE_WINDOW", app.destroy)
    app.mainloop()