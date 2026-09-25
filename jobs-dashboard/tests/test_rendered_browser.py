# -*- coding: utf-8 -*-
"""Tests for the shared rendered-browser lifecycle."""

import unittest

from sources import _rendered


class FakeDriver:
    def __init__(self):
        self.closed = False
        self._collector_browser_slot = True

    def quit(self):
        self.closed = True


class RenderedBrowserTests(unittest.TestCase):
    def test_close_driver_releases_its_slot(self):
        semaphore = _rendered._BROWSER_SEMAPHORE
        self.assertTrue(semaphore.acquire(timeout=0))
        driver = FakeDriver()

        _rendered._close_driver(driver)

        self.assertTrue(driver.closed)
        self.assertTrue(semaphore.acquire(timeout=0))
        semaphore.release()

    def test_close_driver_is_idempotent_for_unmanaged_driver(self):
        driver = FakeDriver()
        driver._collector_browser_slot = False

        _rendered._close_driver(driver)

        self.assertTrue(driver.closed)


if __name__ == "__main__":
    unittest.main()
