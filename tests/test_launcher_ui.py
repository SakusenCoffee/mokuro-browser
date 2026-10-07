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
        history.add("a" * 64, "page", ["日本語、かな！"], "Manga test page")
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
            line_id = int(route.rsplit("/", 1)[1])
            return history.delete(line_id) if value["action"] == "delete" else history.edit(line_id, value["text"])

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

        def create_root():
            nonlocal window
            window = original_root()
            window.after(700, lambda: check(lambda: inspect_server(window)))
            return window

        def inspect_server(window):
            assert active
            capture(window, "/tmp/mokuro-launcher-server.png")
            notebook = find(window, ttk.Notebook)
            notebook.select(1)
            window.after(500, lambda: check(lambda: edit_line(window)))

        def edit_line(window):
            tree = find(window, ttk.Treeview)
            assert len(tree.get_children()) == 1
            tree.selection_set(tree.get_children()[0])
            window.update()
            editor = find(tree.master.master, tk.Text)
            editor.delete("1.0", "end")
            editor.insert("1.0", "猫！")
            find(window, ttk.Button, "Save changes").invoke()
            window.after(500, lambda: check(lambda: delete_line(window)))

        def delete_line(window):
            assert history.list()["totals"]["characters"] == 1
            capture(window, "/tmp/mokuro-launcher-history.png")
            find(window, ttk.Button, "Delete selected line").invoke()
            window.after(500, lambda: check(lambda: change_gpu(window)))

        def change_gpu(window):
            assert history.list()["totals"]["characters"] == 0
            find(window, ttk.Notebook).select(0)
            find(window, ttk.Checkbutton, "Use GPU for OCR when available").invoke()
            window.after(500, lambda: check(lambda: finish(window)))

        def finish(window):
            assert launcher.use_gpu(record) is False
            assert active, "GPU setting must restart a running server"
            window.destroy()

        with mock.patch.object(tk, "Tk", create_root), \
             mock.patch.object(launcher, "installed", return_value=record), \
             mock.patch.object(launcher, "control", side_effect=control), \
             mock.patch.object(launcher, "request", side_effect=request), \
             mock.patch.object(main, "bundled_version", return_value="test"):
            args = SimpleNamespace(fresh=False, root=folder, gui_smoke_test=False, gui_cycle_test=False, report=None)
            main.gui(args)
        if failures:
            raise failures[0]
        print("PASS: actual launcher tabs, history edit/delete, totals, persistent GPU switch and server restart")


if __name__ == "__main__":
    main_test()
