"""Read system utilization at most once per two seconds, without GPU work."""
import ctypes
from pathlib import Path
import sys
import threading
import time

import psutil


class Utilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class LoadMonitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.previous = None
        self.updated = 0
        self.value = {"cpu": None, "gpu": None}
        self.gpu_paths = list(Path("/sys/class/drm").glob("card*/device/gpu_busy_percent")) if sys.platform.startswith("linux") else []
        self.nvml = None
        self.gpu_checked = False

    def gpu_load(self):
        values = []
        for path in self.gpu_paths:
            try:
                values.append(float(path.read_text().strip()))
            except (OSError, ValueError):
                pass
        if not self.gpu_checked:
            self.gpu_checked = True
            for library in (["nvml.dll"] if sys.platform == "win32" else ["libnvidia-ml.so.1"]):
                try:
                    candidate = ctypes.CDLL(library)
                    if candidate.nvmlInit_v2() == 0:
                        self.nvml = candidate
                        break
                except (OSError, AttributeError):
                    pass
        if self.nvml:
            try:
                count = ctypes.c_uint()
                if self.nvml.nvmlDeviceGetCount_v2(ctypes.byref(count)) == 0:
                    for index in range(count.value):
                        handle, usage = ctypes.c_void_p(), Utilization()
                        if (self.nvml.nvmlDeviceGetHandleByIndex_v2(ctypes.c_uint(index), ctypes.byref(handle)) == 0
                                and self.nvml.nvmlDeviceGetUtilizationRates(handle, ctypes.byref(usage)) == 0):
                            values.append(float(usage.gpu))
            except (OSError, AttributeError):
                pass
        return max(values) if values else None

    def sample(self):
        with self.lock:
            now = time.monotonic()
            if self.updated and now - self.updated < 2:
                return self.value.copy()
            cpu = None
            times = psutil.cpu_times()
            total = sum(times) - getattr(times, "guest", 0) - getattr(times, "guest_nice", 0)
            idle = times.idle + getattr(times, "iowait", 0)
            if self.previous:
                elapsed = total - self.previous[0]
                if elapsed > 0:
                    cpu = round(max(0, min(100, 100 * (1 - (idle - self.previous[1]) / elapsed))), 1)
            self.previous = (total, idle)
            self.value = {"cpu": cpu, "gpu": self.gpu_load()}
            self.updated = now
            return self.value.copy()
