"""Exercise the real desktop widgets against isolated reading history.

Requires a display. Never installs an app, registers browsers, or starts OCR.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlsplit

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / "src")]
from installer import main, launcher
from mokuro_browser.history import ReadingHistory


def main_test():
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        token = folder / "token"
        token.write_text("a" * 48)
        (folder / "host-config.json").write_text(json.dumps({"token_file": str(token), "port": 8766}))
        record = {"native_host": str(folder / "helper")}
        history = ReadingHistory(folder / "history.sqlite3")
        history.add("a" * 64, "page", ["日本語、かな！", "カタカナ。"], "Manga test page")
        history.add("b" * 64, "page-2", ["猫、です！", "ネコ。"], "Manga test page 2")
        health = {"model": "ready", "device": "cuda:0", "usage": {"cpu": 8, "gpu": 12}}
        active = False
        failures = []
        window = None
        original_root = tk.Tk

        def control(record, action):
            nonlocal active
            if action == "start": active = True
            if action == "stop": active = False
            return {"running": active, "health": health}

        def request(record, path, value=None):
            if path == "/health": return health
            route = urlsplit(path).path
            if route == "/history": return history.list()
            if route == "/history/delete": return history.delete_pages(value["page_ids"])
            page_id = route.rsplit("/", 1)[1]
            return history.edit(page_id, value["text"])

        def widgets(parent):
            for widget in parent.winfo_children():
                yield widget
                yield from widgets(widget)

        def find(root, kind, text=None):
            return next(widget for widget in widgets(root) if isinstance(widget, kind)
                        and (text is None or widget.cget("text") == text))

        def capture(root, path):
            root.update_idletasks()
            subprocess.run(["import", "-window", str(root.winfo_id()), path], check=True, timeout=10)

        def check(callback):
            try:
                callback()
            except Exception as error:
                failures.append(error)
                window.destroy()

        def create_root(*args, **kwargs):
            nonlocal window
            window = original_root(*args, **kwargs)
            window.after(700, lambda: check(lambda: inspect_server(window)))
            return window

        def inspect_server(window):
            assert active
            reader_buttons = [widget for widget in widgets(window)
                              if isinstance(widget, ttk.Button) and widget.cget("text") == "Open live reader"]
            assert len(reader_buttons) == 2
            assert all(not widget.instate(["disabled"]) for widget in reader_buttons)
            reader_buttons[0].invoke()
            capture(window, "/tmp/mokuro-launcher-server.png")
            notebook = find(window, ttk.Notebook)
            notebook.select(1)
            window.after(500, lambda: check(lambda: edit_page(window)))

        def edit_page(window):
            tree = find(window, ttk.Treeview)
            assert len(tree.get_children()) == 2, "One table row per page, not per OCR line"
            assert "words" not in tree.cget("columns")
            assert "hiragana" in tree.cget("columns") and "katakana" in tree.cget("columns")
            tree.selection_set("a" * 64)
            window.update()
            editor = find(tree.master.master, tk.Text)
            assert editor.get("1.0", "end-1c") == "日本語、かな！\nカタカナ。"
            editor.delete("1.0", "end")
            editor.insert("1.0", "猫！\nひらがな カタカナ")
            find(tree.master.master, ttk.Button, "Refresh").invoke()
            window.after(300, lambda: check(lambda: save_page(window)))

        def save_page(window):
            tree = find(window, ttk.Treeview)
            editor = find(tree.master.master, tk.Text)
            assert editor.get("1.0", "end-1c") == "猫！\nひらがな カタカナ", "Refresh must preserve unsaved edits"
            find(window, ttk.Button, "Save changes").invoke()
            window.after(500, lambda: check(lambda: delete_pages(window)))

        def delete_pages(window):
            saved = history.list()
            assert saved["totals"]["characters"] == 14
            assert saved["totals"]["hiragana"] == 6
            assert saved["totals"]["katakana"] == 6
            delete_button = find(window, ttk.Button, "Delete selected pages")
            assert delete_button.winfo_rooty() + delete_button.winfo_height() < window.winfo_rooty() + window.winfo_height(), "Delete button must fit in the window"
            assert find(find(window, ttk.Treeview).master.master, tk.Text).winfo_height() >= 85
            capture(window, "/tmp/mokuro-launcher-history.png")
            tree = find(window, ttk.Treeview)
            find(tree.master.master, ttk.Button, "Open live reader").invoke()
            tree.selection_set(tree.get_children())
            window.update()
            assert find(window, ttk.Button, "Save changes").instate(["disabled"])
            tree.focus_force()
            confirm.return_value = False
            tree.event_generate("<Delete>")
            assert history.list()["totals"]["pages"] == 2, "Cancelled deletion must preserve pages"
            confirm.return_value = True
            tree.event_generate("<Delete>")
            window.after(500, lambda: check(lambda: change_gpu(window)))

        def change_gpu(window):
            assert history.list()["totals"]["characters"] == 0
            find(window, ttk.Notebook).select(0)
            find(window, ttk.Checkbutton, "Use GPU for OCR when available").invoke()
            window.after(500, lambda: check(lambda: finish(window)))

        def finish(window):
            assert launcher.use_gpu(record) is False
            assert active, "GPU setting must restart a running server"
            assert open_dashboard.call_count == 2, "Live reader button works from both launcher tabs"
            open_dashboard.side_effect = RuntimeError("Default browser is unavailable")
            find(window, ttk.Button, "Open live reader").invoke()
            window.after(300, lambda: check(lambda: finish_fallback(window)))

        def finish_fallback(window):
            assert window.clipboard_get() == launcher.dashboard_url(record), "Browser failures must offer a usable local link"
            window.destroy()

        with mock.patch.object(tk, "Tk", create_root), \
             mock.patch.object(launcher, "installed", return_value=record), \
             mock.patch.object(launcher, "control", side_effect=control), \
             mock.patch.object(launcher, "request", side_effect=request), \
             mock.patch.object(launcher, "open_dashboard") as open_dashboard, \
             mock.patch.object(messagebox, "askyesno", return_value=True) as confirm, \
             mock.patch.object(main, "bundled_version", return_value="test"):
            args = SimpleNamespace(fresh=False, root=folder, gui_smoke_test=False, gui_cycle_test=False, report=None)
            main.gui(args)
        if failures:
            raise failures[0]
        print("PASS: launcher layout, whole-page edit, kana counts, multi-page Delete key, both live reader buttons and GPU restart")


if __name__ == "__main__":
    main_test()
