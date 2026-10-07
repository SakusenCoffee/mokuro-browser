from collections import namedtuple
import unittest
from unittest import mock

from mokuro_browser.monitor import LoadMonitor


class LoadMonitorTests(unittest.TestCase):
    def test_samples_are_cached_and_do_not_block_for_measurement(self):
        Times = namedtuple("Times", "user system idle")
        monitor = LoadMonitor()
        with mock.patch("mokuro_browser.monitor.time.monotonic", side_effect=[10, 11, 13]), \
             mock.patch("mokuro_browser.monitor.psutil.cpu_times", side_effect=[Times(10, 5, 85), Times(20, 10, 170)]) as cpu, \
             mock.patch.object(monitor, "gpu_load", return_value=25) as gpu:
            self.assertIsNone(monitor.sample()["cpu"])
            self.assertEqual(monitor.sample()["gpu"], 25)
            self.assertEqual(monitor.sample()["cpu"], 15)
            self.assertEqual(cpu.call_count, 2)
            self.assertEqual(gpu.call_count, 2)
