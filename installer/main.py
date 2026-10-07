"""Entry point for the downloadable installer; no system Python required."""
import argparse
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading

from installer import core

def payload():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    folder = root / "payload" if getattr(sys, "frozen", False) else root / "build/installer-payload"
    wheels = sorted(folder.glob("mokuro_browser-*-py3-none-any.whl"))
    if len(wheels) != 1:
        raise RuntimeError("Installer payload is missing or ambiguous. Build the package first.")
    uv = root / "payload" / ("uv.exe" if os.name == "nt" else "uv")
    if not uv.is_file():
        location = shutil.which("uv")
        if not location:
            raise RuntimeError("uv is missing from the installer payload.")
        uv = Path(location)
    native_host = root / "payload" / ("MokuroBrowserNativeHost.exe" if os.name == "nt" else "MokuroBrowserNativeHost")
    return uv, wheels[0], native_host if native_host.is_file() else None

def execute(args, log):
    if args.uninstall:
        core.uninstall(root=args.root, log=log)
        return {"removed": True}
    uv, wheel, native_host = payload()
    return core.install(uv, wheel, root=args.root, bin_dir=args.bin_dir,
                        reuse=not args.fresh, python=args.python,
                        autostart=args.autostart, modify_path=not args.no_path,
                        state_dir=args.state_dir, native_host=native_host, log=log)

def open_folder(folder):
    if os.name == "nt":
        os.startfile(folder)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder], env=core.child_environment())

def gui(args):
    import tkinter as tk
    from tkinter import ttk
    from tkinter.scrolledtext import ScrolledText
    root = tk.Tk()
    root.title("Mokuro Browser Setup")
    root.geometry("760x590")
    root.minsize(640, 500)
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Mokuro Browser", font=("", 22)).pack(anchor="w")
    ttk.Label(frame, text="Install Python, Mokuro and the local OCR server for this user.\nInternet is needed for downloads. No administrator access is required.").pack(anchor="w", pady=(8, 15))
    reuse = tk.BooleanVar(value=not args.fresh)
    ttk.Checkbutton(frame, text="Reuse an existing Mokuro / GPU environment when available", variable=reuse).pack(anchor="w")
    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=12)
    output = ScrolledText(frame, height=13, wrap="word", state="disabled")
    output.pack(fill="both", expand=True)
    actions = ttk.Frame(frame)
    actions.pack(fill="x", pady=(10, 0))
    messages = queue.Queue()
    running = False
    progress = ttk.Progressbar(frame, mode="indeterminate")
    progress.pack(fill="x", before=output, pady=(0, 8))
    def write(text):
        output.configure(state="normal")
        output.insert("end", text + "\n")
        output.see("end")
        output.configure(state="disabled")
    def start(removing=False):
        nonlocal running
        running = True
        progress.start()
        install_button.configure(state="disabled")
        remove_button.configure(state="disabled")
        args.uninstall, args.fresh = removing, not reuse.get()
        def work():
            try:
                messages.put(("done", execute(args, lambda line: messages.put(("log", line)))))
            except Exception as error:
                messages.put(("error", str(error)))
        threading.Thread(target=work, daemon=True).start()
    install_button = ttk.Button(buttons, text="Install / update", command=start)
    install_button.pack(side="left")
    remove_button = ttk.Button(buttons, text="Uninstall managed installation", command=lambda: start(True))
    remove_button.pack(side="left", padx=10)
    def poll():
        nonlocal running
        while not messages.empty():
            kind, value = messages.get_nowait()
            if kind == "log":
                write(value)
                continue
            running = False
            progress.stop()
            install_button.configure(state="normal")
            remove_button.configure(state="normal")
            for widget in actions.winfo_children():
                widget.destroy()
            if kind == "error":
                write("Installation failed:\n" + value + "\nYou can retry without removing your existing installation.")
            elif value.get("removed"):
                write("Uninstall complete.")
            else:
                write("\nNext: load the extension folder in your browser, then paste this pairing code into the extension popup.")
                write("Extension folder: " + value["extension"])
                write("Pairing code: " + value["pairing_code"])
                write("Use the Server button in the Local Mokuro extension to start OCR when you need it.")
                def copy():
                    root.clipboard_clear()
                    root.clipboard_append(value["pairing_code"])
                ttk.Button(actions, text="Copy pairing code", command=copy).pack(side="left")
                ttk.Button(actions, text="Open extension folder", command=lambda: open_folder(value["extension"])).pack(side="left", padx=8)
                import webbrowser
                ttk.Button(actions, text="Browser instructions", command=lambda: webbrowser.open("https://github.com/SakusenCoffee/mokuro-browser#install-the-browser-extension")).pack(side="left")
        root.after(100, poll)
    root.protocol("WM_DELETE_WINDOW", lambda: write("Wait for installation to finish before closing.") if running else root.destroy())
    poll()
    if args.gui_smoke_test:
        if args.report:
            core.atomic_write(args.report, json.dumps({"gui": True}))
        root.after(500, root.destroy)
    root.mainloop()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", action="store_true", help="Run without the graphical interface")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--fresh", action="store_true", help="Use private Python and CPU dependencies")
    parser.add_argument("--autostart", action="store_true", help="Also start the server automatically at login")
    parser.add_argument("--no-autostart", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-path", action="store_true")
    parser.add_argument("--python", type=Path, help="Reuse Mokuro from this interpreter")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--bin-dir", type=Path)
    parser.add_argument("--state-dir", type=Path, help="Use isolated server state (for testing)")
    parser.add_argument("--report", type=Path, help="Write a private installation report")
    parser.add_argument("--gui-smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.cli:
        gui(args)
        return
    try:
        result = execute(args, lambda line: print(line, flush=True))
        if args.report:
            core.atomic_write(args.report, json.dumps(result, indent=2))
        if not result.get("removed"):
            print("Extension folder:", result["extension"])
            print("Pairing code:", result["pairing_code"])
    except Exception as error:
        print("Setup failed:", error, file=sys.stderr)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
