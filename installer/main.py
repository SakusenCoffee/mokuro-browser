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
    root.configure(bg="#101919")
    assets = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    icon = assets / ("payload/icon-128.png" if getattr(sys, "frozen", False) else "extension/icon-128.png")
    root.app_icon = tk.PhotoImage(file=str(icon))
    root.iconphoto(True, root.app_icon)
    root.geometry("980x760")
    root.minsize(760, 600)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background="#101919", foreground="#e8f1ee", fieldbackground="#1b2a28", bordercolor="#385850",
                    font=("Segoe UI", 10))
    style.configure("TFrame", background="#101919")
    style.configure("TLabel", background="#101919", foreground="#d7e7e1")
    style.configure("Title.TLabel", font=("Segoe UI", 26, "bold"), foreground="#ffffff")
    style.configure("Subtle.TLabel", foreground="#a6beb6")
    style.configure("TButton", padding=(13, 8), background="#25473f", foreground="#f4fbf8", bordercolor="#5eaa91")
    style.map("TButton", background=[("active", "#367864"), ("disabled", "#26332f")], foreground=[("disabled", "#71847e")])
    style.configure("TCheckbutton", background="#101919", foreground="#d7e7e1")
    style.map("TCheckbutton", background=[("active", "#101919")])
    style.configure("TNotebook", background="#101919", borderwidth=0)
    style.configure("TNotebook.Tab", padding=(16, 9), background="#1a2926", foreground="#abc1ba")
    style.map("TNotebook.Tab", background=[("selected", "#2a5147")], foreground=[("selected", "#ffffff")])
    style.configure("Treeview", background="#172522", fieldbackground="#172522", foreground="#e6f0ec", rowheight=31)
    style.configure("Treeview.Heading", background="#29443e", foreground="#eff8f4", relief="flat")
    style.map("Treeview", background=[("selected", "#356c5c")], foreground=[("selected", "#ffffff")])
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=12, pady=12)
    frame = ttk.Frame(notebook, padding=20)
    history_frame = ttk.Frame(notebook, padding=20)
    notebook.add(frame, text="Server")
    notebook.add(history_frame, text="Reading history")
    ttk.Label(frame, text="Mokuro Browser", style="Title.TLabel").pack(anchor="w")
    ttk.Label(frame, text="Your private manga OCR control room. The server runs while this window is open.", style="Subtle.TLabel").pack(anchor="w", pady=(4, 16))
    reuse = tk.BooleanVar(value=not args.fresh)
    ttk.Checkbutton(frame, text="Reuse an existing Mokuro / GPU environment when available", variable=reuse).pack(anchor="w")
    gpu_enabled = tk.BooleanVar(value=True)
    gpu_toggle = ttk.Checkbutton(frame, text="Use GPU for OCR when available", variable=gpu_enabled,
                                command=lambda: change_gpu())
    gpu_toggle.pack(anchor="w", pady=(8, 0))
    gpu_toggle.configure(state="disabled")
    ttk.Label(frame, text="Turning this off uses CPU. Changing it restarts the server and reloads the models.", style="Subtle.TLabel").pack(anchor="w")
    server_status = tk.StringVar(value="Checking installation…")
    ttk.Label(frame, textvariable=server_status, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(14, 4))
    load_status = tk.StringVar(value="System load · CPU —   GPU —")
    ttk.Label(frame, textvariable=load_status, style="Subtle.TLabel").pack(anchor="w", pady=(0, 10))
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
    buttons.pack(fill="x", pady=(8, 12))
    ttk.Label(frame, text="Activity logs", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(2, 5))
    log_tabs = ttk.Notebook(frame)
    log_tabs.pack(fill="both", expand=True)
    setup_log_frame = ttk.Frame(log_tabs, padding=1)
    server_log_frame = ttk.Frame(log_tabs, padding=1)
    log_tabs.add(setup_log_frame, text="Setup activity")
    log_tabs.add(server_log_frame, text="Server log")
    log_tabs.select(server_log_frame)
    output = ScrolledText(setup_log_frame, height=12, wrap="word", state="disabled", bg="#121d1b", fg="#dbe9e4",
                          insertbackground="#e8f1ee", relief="flat", padx=12, pady=10)
    output.pack(fill="both", expand=True)
    server_output = ScrolledText(server_log_frame, height=12, wrap="word", state="disabled", bg="#121d1b", fg="#dbe9e4",
                                 insertbackground="#e8f1ee", relief="flat", padx=12, pady=10)
    server_output.pack(fill="both", expand=True)
    actions = ttk.Frame(frame)
    actions.pack(fill="x", pady=(10, 0))
    messages = queue.Queue()
    running = False
    owned_server = False
    server_pending = False
    observe_pending = False
    server_generation = 0
    installed_record = None
    history_pending = False
    history_offset = 0
    history_page_size = 200
    history_total_lines = 0
    ttk.Label(history_frame, text="Reading history", font=("", 20)).pack(anchor="w")
    history_totals = tk.StringVar(value="Characters 0     Words 0     Kanji 0     Kana 0")
    ttk.Label(history_frame, textvariable=history_totals, font=("", 13)).pack(anchor="w", pady=(12, 4))
    ttk.Label(history_frame, text="Recognized text, counted once per page. Spaces and punctuation are excluded; words use Japanese segmentation.",
              wraplength=800).pack(anchor="w", pady=(0, 12))
    table_frame = ttk.Frame(history_frame)
    table_frame.pack(fill="both", expand=True)
    columns = ("text", "characters", "words", "kanji", "kana", "source")
    history_table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
    for column, label, width in (("text", "Saved text", 320), ("characters", "Chars", 55), ("words", "Words", 55),
                                 ("kanji", "Kanji", 55), ("kana", "Kana", 55), ("source", "Page", 170)):
        history_table.heading(column, text=label)
        history_table.column(column, width=width, minwidth=45, anchor="w" if column in ("text", "source") else "center")
    history_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=history_table.yview)
    history_table.configure(yscrollcommand=history_scroll.set)
    history_table.pack(side="left", fill="both", expand=True)
    history_scroll.pack(side="right", fill="y")
    page_controls = ttk.Frame(history_frame)
    page_controls.pack(fill="x", pady=8)
    previous_history = ttk.Button(page_controls, text="Newer lines", command=lambda: history_page(-1))
    previous_history.pack(side="left")
    next_history = ttk.Button(page_controls, text="Older lines", command=lambda: history_page(1))
    next_history.pack(side="left", padx=8)
    ttk.Button(page_controls, text="Refresh", command=lambda: refresh_history()).pack(side="right")
    history_note = tk.StringVar(value="Open the server to view your saved reading history.")
    ttk.Label(history_frame, textvariable=history_note, wraplength=800).pack(anchor="w", pady=(0, 8))
    ttk.Label(history_frame, text="Edit selected line:").pack(anchor="w")
    line_editor = ScrolledText(history_frame, height=4, wrap="word")
    line_editor.pack(fill="x", pady=(4, 8))
    history_actions = ttk.Frame(history_frame)
    history_actions.pack(fill="x")
    save_line = ttk.Button(history_actions, text="Save changes", command=lambda: change_line("edit"))
    save_line.pack(side="left")
    delete_line = ttk.Button(history_actions, text="Delete selected line", command=lambda: change_line("delete"))
    delete_line.pack(side="left", padx=8)
    save_line.configure(state="disabled")
    delete_line.configure(state="disabled")
    history_rows = {}
    editing_id = None

    def select_line(event=None):
        nonlocal editing_id
        selected = history_table.selection()
        line_id = selected[0] if selected else None
        if line_id == editing_id:
            return
        editing_id = line_id
        line_editor.delete("1.0", "end")
        if line_id and line_id in history_rows:
            line_editor.insert("1.0", history_rows[line_id]["text"])
        state = "normal" if line_id and not history_pending else "disabled"
        save_line.configure(state=state)
        delete_line.configure(state=state)

    history_table.bind("<<TreeviewSelect>>", select_line)

    def refresh_history():
        nonlocal history_pending
        if history_pending or not installed_record or running or server_pending:
            return
        history_pending = True
        record, offset = installed_record.copy(), history_offset
        def work():
            try:
                result = launcher.request(record, f"/history?offset={offset}&limit={history_page_size}")
                messages.put(("history", result))
            except Exception as error:
                messages.put(("history_error", "Could not load reading history: " + str(error)))
        threading.Thread(target=work, daemon=True).start()

    def history_page(direction):
        nonlocal history_offset
        if not history_pending:
            history_offset = max(0, history_offset + direction * history_page_size)
            refresh_history()

    def change_line(action):
        nonlocal history_pending
        selected = history_table.selection()
        if history_pending or not installed_record or not selected:
            return
        line_id = selected[0]
        value = {"action": action}
        if action == "edit":
            value["text"] = line_editor.get("1.0", "end-1c")
            if not value["text"].strip():
                history_note.set("Enter some text, or use Delete selected line.")
                return
        history_pending = True
        save_line.configure(state="disabled")
        delete_line.configure(state="disabled")
        record = installed_record.copy()
        def work():
            try:
                launcher.request(record, f"/history/{line_id}", value)
                messages.put(("history_changed", action))
            except Exception as error:
                messages.put(("history_error", "Could not change the saved line: " + str(error)))
        threading.Thread(target=work, daemon=True).start()

    def show_server(result):
        active, health = result["running"], result.get("health", {})
        if not active:
            server_status.set("Server is off")
        elif health.get("model") == "ready":
            device = health.get("device", "") or ""
            mode = "GPU" if device.startswith(("cuda", "mps")) else "CPU"
            server_status.set(f"Server running · models ready · {mode}")
        elif health.get("model") == "error":
            server_status.set("Server running · models could not load: " + str(health.get("model_error", "")))
        elif health.get("model") == "loading":
            server_status.set("Server running · loading OCR models…")
        else:
            server_status.set("Server running · older server detected. Stop and restart it using this launcher.")
        usage = health.get("usage", {})
        def percent(value):
            return f"{value:.0f}%" if isinstance(value, (int, float)) else "unavailable"
        load_status.set(f"System load · CPU {percent(usage.get('cpu'))}   GPU {percent(usage.get('gpu'))}" if active
                        else "System load · CPU —   GPU —")

    def change_gpu():
        nonlocal server_pending, server_generation
        if running or server_pending or not installed_record:
            return
        server_pending = True
        server_generation += 1
        gpu_toggle.configure(state="disabled")
        server_button.configure(state="disabled")
        server_status.set("Applying GPU setting and reloading models…")
        record, enabled = installed_record.copy(), gpu_enabled.get()
        def work():
            try:
                launcher.set_gpu(record, enabled)
                active = launcher.control(record, "status")["running"]
                if active:
                    launcher.control(record, "stop")
                    result = launcher.control(record, "start")
                else:
                    result = {"running": False}
                messages.put(("server", ("start" if active else "stop", result, active)))
            except Exception as error:
                messages.put(("server_error", str(error)))
        threading.Thread(target=work, daemon=True).start()
    progress = ttk.Progressbar(frame, mode="indeterminate")
    def write(text):
        output.configure(state="normal")
        output.insert("end", text + "\n")
        output.see("end")
        output.configure(state="disabled")
    server_log_text = None
    def refresh_server_log():
        nonlocal server_log_text
        if installed_record:
            try:
                path = Path(launcher.host_config(installed_record).get("log_file", ""))
                text = path.read_text(encoding="utf-8", errors="replace")[-30000:] if path.is_file() else "The server log will appear here after it starts."
            except (OSError, ValueError, KeyError):
                text = "The server log is unavailable."
            if text != server_log_text:
                server_log_text = text
                server_output.configure(state="normal")
                server_output.delete("1.0", "end")
                server_output.insert("end", text)
                server_output.see("end")
                server_output.configure(state="disabled")
    def show_installation(record):
        nonlocal installed_record
        installed_record = record
        code.set(launcher.pairing_code(record))
        gpu_enabled.set(launcher.use_gpu(record))
        gpu_toggle.configure(state="normal")
        server_status.set("Server is off")
    def server_action(action):
        nonlocal server_pending, server_generation
        if server_pending or not installed_record:
            return
        server_pending = True
        server_generation += 1
        server_button.configure(state="disabled")
        gpu_toggle.configure(state="disabled")
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
        nonlocal running, server_generation
        if running or server_pending:
            return
        running = True
        server_generation += 1
        progress.pack(fill="x", before=log_tabs, pady=(0, 8))
        progress.start()
        install_button.configure(state="disabled")
        remove_button.configure(state="disabled")
        server_button.configure(state="disabled")
        gpu_toggle.configure(state="disabled")
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
    dashboard_button = ttk.Button(buttons, text="Open live reader", command=lambda: launcher.open_dashboard(installed_record))
    dashboard_button.pack(side="right")
    dashboard_button.configure(state="disabled")
    def poll():
        nonlocal running, owned_server, server_pending, installed_record, history_pending, history_total_lines, observe_pending
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
                show_server(result)
                server_button.configure(text="Stop server" if active else "Start server", state="normal")
                gpu_toggle.configure(state="normal")
                dashboard_button.configure(state="normal" if active else "disabled")
                refresh_history()
                continue
            if kind == "server_error":
                server_pending = False
                server_status.set("Server could not start")
                server_button.configure(state="normal")
                gpu_toggle.configure(state="normal")
                write("Server error: " + value)
                continue
            if kind == "observed":
                observe_pending = False
                generation, result = value
                if generation == server_generation and not server_pending and not running:
                    active = result["running"]
                    if not active:
                        owned_server = False
                    show_server(result)
                    server_button.configure(text="Stop server" if active else "Start server", state="normal")
                    dashboard_button.configure(state="normal" if active else "disabled")
                continue
            if kind == "history":
                history_pending = False
                history_total_lines = value["totals"]["lines"]
                totals = value["totals"]
                history_totals.set("     ".join(f"{name.title()} {totals[name]:,}" for name in ("characters", "words", "kanji", "kana")))
                new_rows = {str(row["id"]): row for row in value["lines"]}
                for line_id in history_table.get_children():
                    if line_id not in new_rows:
                        history_table.delete(line_id)
                for position, (line_id, row) in enumerate(new_rows.items()):
                    values = (row["text"], row["characters"], row["words"], row["kanji"], row["kana"], row["title"])
                    if history_table.exists(line_id):
                        history_table.item(line_id, values=values)
                        history_table.move(line_id, "", position)
                    else:
                        history_table.insert("", position, iid=line_id, values=values)
                history_rows.clear()
                history_rows.update(new_rows)
                previous_history.configure(state="normal" if history_offset else "disabled")
                next_history.configure(state="normal" if history_offset + history_page_size < history_total_lines else "disabled")
                history_note.set(f"{history_total_lines:,} saved lines across {totals['pages']:,} pages · totals update when you edit or delete a line.")
                select_line()
                if history_table.selection():
                    save_line.configure(state="normal")
                    delete_line.configure(state="normal")
                continue
            if kind in ("history_changed", "history_error"):
                history_pending = False
                if kind == "history_changed":
                    history_note.set("Changes saved." if value == "edit" else "Saved line deleted.")
                    refresh_history()
                else:
                    history_note.set(value)
                    if history_table.selection():
                        save_line.configure(state="normal")
                        delete_line.configure(state="normal")
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
            progress.pack_forget()
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
                dashboard_button.configure(state="disabled")
                gpu_toggle.configure(state="disabled")
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
        nonlocal observe_pending
        if installed_record and not running and not server_pending and not observe_pending:
            observe_pending = True
            record, generation = installed_record.copy(), server_generation
            def work():
                try:
                    messages.put(("observed", (generation, {"running": True, "health": launcher.request(record, "/health")})))
                except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                    messages.put(("observed", (generation, {"running": False})))
            threading.Thread(target=work, daemon=True).start()
        if notebook.select() == str(history_frame):
            refresh_history()
        refresh_server_log()
        root.after(2500, refresh_server)
    notebook.bind("<<NotebookTabChanged>>", lambda event: refresh_history() if notebook.select() == str(history_frame) else None)
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
        deadline = time.monotonic() + 280
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
