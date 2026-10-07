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
import time

from installer import core, launcher

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

def bundled_version():
    return payload()[1].name.split("-")[1]

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
    root.title("Mokuro Browser")
    root.geometry("760x590")
    root.minsize(640, 500)
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Mokuro Browser", font=("", 22)).pack(anchor="w")
    ttk.Label(frame, text="Launch this app whenever you want to read manga. The local server runs while this window is open.").pack(anchor="w", pady=(8, 12))
    reuse = tk.BooleanVar(value=not args.fresh)
    ttk.Checkbutton(frame, text="Reuse an existing Mokuro / GPU environment when available", variable=reuse).pack(anchor="w")
    server_status = tk.StringVar(value="Checking installation…")
    ttk.Label(frame, textvariable=server_status).pack(anchor="w", pady=(10, 4))
    code = tk.StringVar()
    code_row = ttk.Frame(frame)
    code_row.pack(fill="x", pady=(0, 8))
    ttk.Label(code_row, text="Connect code:").pack(side="left")
    ttk.Entry(code_row, textvariable=code, state="readonly").pack(side="left", fill="x", expand=True, padx=8)
    def copy_code():
        if code.get():
            root.clipboard_clear()
            root.clipboard_append(code.get())
    ttk.Button(code_row, text="Copy", command=copy_code).pack(side="left")
    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=12)
    output = ScrolledText(frame, height=13, wrap="word", state="disabled")
    output.pack(fill="both", expand=True)
    actions = ttk.Frame(frame)
    actions.pack(fill="x", pady=(10, 0))
    messages = queue.Queue()
    running = False
    owned_server = False
    server_pending = False
    installed_record = None
    progress = ttk.Progressbar(frame, mode="indeterminate")
    progress.pack(fill="x", before=output, pady=(0, 8))
    def write(text):
        output.configure(state="normal")
        output.insert("end", text + "\n")
        output.see("end")
        output.configure(state="disabled")
    def show_installation(record):
        nonlocal installed_record
        installed_record = record
        code.set(launcher.pairing_code(record))
        server_status.set("Server is off")
    def server_action(action):
        nonlocal server_pending
        if server_pending or not installed_record:
            return
        server_pending = True
        server_button.configure(state="disabled")
        server_status.set("Starting server…" if action == "start" else "Stopping server…")
        record = installed_record.copy()
        def work():
            try:
                before = launcher.control(record, "status") if action == "start" else None
                result = launcher.control(record, action)
                messages.put(("server", (action, result, bool(before and not before["running"]))))
            except Exception as error:
                messages.put(("server_error", str(error)))
        threading.Thread(target=work, daemon=True).start()
    def start(removing=False):
        nonlocal running
        if running or server_pending:
            return
        running = True
        progress.start()
        install_button.configure(state="disabled")
        remove_button.configure(state="disabled")
        server_button.configure(state="disabled")
        args.uninstall, args.fresh = removing, not reuse.get()
        def work():
            try:
                current = launcher.installed(args.root)
                if current and launcher.control(current, "status")["running"]:
                    launcher.control(current, "stop")
                messages.put(("done", execute(args, lambda line: messages.put(("log", line)))))
            except Exception as error:
                messages.put(("error", str(error)))
        threading.Thread(target=work, daemon=True).start()
    install_button = ttk.Button(buttons, text="Install / update", command=start)
    install_button.pack(side="left")
    remove_button = ttk.Button(buttons, text="Uninstall managed installation", command=lambda: start(True))
    remove_button.pack(side="left", padx=10)
    server_button = ttk.Button(buttons, text="Start server", command=lambda: server_action(
        "stop" if server_button.cget("text") == "Stop server" else "start"))
    server_button.pack(side="left", padx=10)
    server_button.configure(state="disabled")
    def poll():
        nonlocal running, owned_server, server_pending, installed_record
        while not messages.empty():
            kind, value = messages.get_nowait()
            if kind == "log":
                write(value)
                continue
            if kind == "server":
                action, result, started_here = value
                server_pending = False
                active = result["running"]
                if action == "start" and started_here:
                    owned_server = True
                if not active:
                    owned_server = False
                server_status.set("Server running · extension can scan" if active else "Server is off")
                server_button.configure(text="Stop server" if active else "Start server", state="normal")
                continue
            if kind == "server_error":
                server_pending = False
                server_status.set("Server could not start")
                server_button.configure(state="normal")
                write("Server error: " + value)
                continue
            if kind == "observed":
                if not server_pending and not running:
                    active = value
                    if not active:
                        owned_server = False
                    server_status.set("Server running · extension can scan" if active else "Server is off")
                    server_button.configure(text="Stop server" if active else "Start server", state="normal")
                continue
            if kind == "closed":
                root.destroy()
                return
            if kind == "close_error":
                server_pending = False
                server_status.set("Could not stop server")
                server_button.configure(state="normal")
                write("Server error: " + value)
                if args.gui_cycle_test:
                    if args.report:
                        core.atomic_write(args.report, json.dumps({"gui_cycle": False, "error": value}))
                    root.destroy()
                continue
            running = False
            progress.stop()
            install_button.configure(state="normal")
            remove_button.configure(state="normal")
            for widget in actions.winfo_children():
                widget.destroy()
            if kind == "error":
                server_status.set("Installation failed")
                write("Installation failed:\n" + value + "\nYou can retry without removing your existing installation.")
            elif value.get("removed"):
                installed_record = None
                owned_server = False
                code.set("")
                server_status.set("Not installed")
                server_button.configure(state="disabled")
                write("Uninstall complete.")
            else:
                record = launcher.installed(args.root)
                show_installation(record)
                write("\nThe server starts now. Load the extension once, then it will recognize this server.")
                write("Extension folder: " + value["extension"])
                ttk.Button(actions, text="Open extension folder", command=lambda: open_folder(value["extension"])).pack(side="left", padx=8)
                import webbrowser
                ttk.Button(actions, text="Browser instructions", command=lambda: webbrowser.open("https://github.com/SakusenCoffee/mokuro-browser#install-the-browser-extension")).pack(side="left")
                server_action("start")
        root.after(100, poll)
    def refresh_server():
        if installed_record and not running and not server_pending:
            record = installed_record.copy()
            def work():
                try:
                    messages.put(("observed", launcher.control(record, "status")["running"]))
                except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                    messages.put(("observed", False))
            threading.Thread(target=work, daemon=True).start()
        root.after(4000, refresh_server)
    def close():
        nonlocal server_pending
        if running or server_pending:
            write("Wait for the current operation to finish before closing.")
        elif owned_server and installed_record:
            server_pending = True
            server_status.set("Stopping server…")
            record = installed_record.copy()
            def work():
                try:
                    launcher.control(record, "stop")
                    messages.put(("closed", None))
                except Exception as error:
                    messages.put(("close_error", str(error)))
            threading.Thread(target=work, daemon=True).start()
        else:
            root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    poll()
    refresh_server()
    if args.gui_smoke_test:
        if args.report:
            core.atomic_write(args.report, json.dumps({"gui": True}))
        root.after(500, root.destroy)
    else:
        current = launcher.installed(args.root, bundled_version())
        if current:
            show_installation(current)
            root.after(150, lambda: server_action("start"))
        else:
            root.after(150, start)
    if args.gui_cycle_test:
        deadline = time.monotonic() + 40
        def check_cycle():
            if server_status.get().startswith("Server running") and len(code.get()) >= 32:
                if args.report:
                    core.atomic_write(args.report, json.dumps({"gui_cycle": True, "connect_code_visible": True}))
                close()
            elif time.monotonic() > deadline:
                if args.report:
                    core.atomic_write(args.report, json.dumps({"gui_cycle": False, "status": server_status.get()}))
                root.destroy()
            else:
                root.after(250, check_cycle)
        root.after(250, check_cycle)
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
    parser.add_argument("--server-action", choices=("status", "start", "stop"),
                        help="Control the installed server without opening the window")
    parser.add_argument("--gui-smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--gui-cycle-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.server_action:
        try:
            record = launcher.installed(args.root)
            if not record:
                raise RuntimeError("No managed Mokuro Browser installation was found.")
            answer = launcher.control(record, args.server_action)
            if args.report:
                core.atomic_write(args.report, json.dumps(answer, indent=2))
            print("Server running" if answer["running"] else "Server off")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            parser.exit(1, f"Server control failed: {error}\n")
        return
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
