"""Login startup for the installing user and their actual Python environment."""
import getpass
import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from .config import atomic_write, config_dir, log_dir

LABEL = "io.github.mokuro-browser"
SERVICE = "mokuro-browser.service"

def command(python=None, logs=None):
    return [str(python or sys.executable), "-u", "-m", "mokuro_browser", "serve",
            "--log-file", str((logs or log_dir()) / "server.log")]

def systemd_quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace(
        "%", "%%").replace("$", "$$").replace("\n", "\\n").replace("\r", "\\r") + '"'

def systemd_unit(args):
    return ("[Unit]\nDescription=Mokuro Browser OCR server\nAfter=network.target\n\n"
            "[Service]\nType=simple\nExecStart=" + " ".join(map(systemd_quote, args)) +
            "\nRestart=on-failure\nRestartSec=3\n\n[Install]\nWantedBy=default.target\n")

def launch_agent(args):
    return plistlib.dumps({"Label": LABEL, "ProgramArguments": args,
                          "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False},
                          "ThrottleInterval": 10})

def windows_identity():
    domain = os.environ.get("USERDOMAIN", "")
    user = getpass.getuser()
    return f"{domain}\\{user}" if domain else user

def task_name(identity):
    return "Mokuro Browser " + hashlib.sha256(identity.encode()).hexdigest()[:12]

def windows_task(args, identity):
    namespace = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", namespace)
    def add(parent, name, text=None, **attrs):
        node = ET.SubElement(parent, f"{{{namespace}}}{name}", attrs)
        node.text = text
        return node
    root = ET.Element(f"{{{namespace}}}Task", {"version": "1.2"})
    triggers = add(root, "Triggers")
    trigger = add(triggers, "LogonTrigger")
    add(trigger, "Enabled", "true")
    add(trigger, "UserId", identity)
    principals = add(root, "Principals")
    principal = add(principals, "Principal", id="CurrentUser")
    add(principal, "UserId", identity)
    add(principal, "LogonType", "InteractiveToken")
    add(principal, "RunLevel", "LeastPrivilege")
    settings = add(root, "Settings")
    add(settings, "MultipleInstancesPolicy", "IgnoreNew")
    add(settings, "DisallowStartIfOnBatteries", "false")
    add(settings, "StopIfGoingOnBatteries", "false")
    add(settings, "ExecutionTimeLimit", "PT0S")
    add(settings, "StartWhenAvailable", "true")
    restart = add(settings, "RestartOnFailure")
    add(restart, "Interval", "PT1M")
    add(restart, "Count", "3")
    actions = add(root, "Actions", Context="CurrentUser")
    action = add(actions, "Exec")
    add(action, "Command", args[0])
    add(action, "Arguments", subprocess.list2cmdline(args[1:]))
    return ET.tostring(root, encoding="utf-16", xml_declaration=True)

def startup_path():
    if sys.platform == "win32":
        return config_dir() / "startup-task.xml"
    if sys.platform == "darwin":
        return Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    if sys.platform.startswith("linux"):
        xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        return xdg / "systemd/user" / SERVICE
    raise RuntimeError("Automatic startup is unavailable on this OS. Use mokuro-browser serve.")

def run(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True)

def install():
    path = startup_path()
    args = command()
    if sys.platform.startswith("linux"):
        if not shutil.which("systemctl") or not Path("/run/systemd/system").exists():
            raise RuntimeError("This Linux computer does not use systemd. Use mokuro-browser serve.")
        run("systemctl", "--user", "show-environment")
        atomic_write(path, systemd_unit(args))
        run("systemctl", "--user", "daemon-reload")
        run("systemctl", "--user", "enable", SERVICE)
        run("systemctl", "--user", "restart", SERVICE)
    elif sys.platform == "darwin":
        domain = f"gui/{os.getuid()}"
        run("launchctl", "bootout", f"{domain}/{LABEL}", check=False)
        atomic_write(path, launch_agent(args))
        run("launchctl", "enable", f"{domain}/{LABEL}")
        run("launchctl", "bootstrap", domain, str(path))
    elif sys.platform == "win32":
        identity = windows_identity()
        atomic_write(path, windows_task(args, identity))
        name = task_name(identity)
        run("schtasks", "/End", "/TN", name, check=False)
        run("schtasks", "/Create", "/TN", name, "/XML", str(path), "/F")
        run("schtasks", "/Run", "/TN", name)
    return path

def remove():
    path = startup_path()
    if sys.platform.startswith("linux"):
        run("systemctl", "--user", "disable", "--now", SERVICE)
    elif sys.platform == "darwin":
        run("launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}", check=False)
    elif sys.platform == "win32":
        name = task_name(windows_identity())
        run("schtasks", "/End", "/TN", name, check=False)
        run("schtasks", "/Delete", "/TN", name, "/F")
    path.unlink(missing_ok=True)
    if sys.platform.startswith("linux"):
        run("systemctl", "--user", "daemon-reload")
