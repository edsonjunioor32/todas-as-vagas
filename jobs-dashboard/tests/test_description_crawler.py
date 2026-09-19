import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from description_crawler import RobotsCache


class RobotsCacheTests(unittest.TestCase):
    def test_robots_fetch_uses_finite_timeout_and_caches_policy(self):
        robots = b"User-agent: crawler-test\nDisallow: /private\nAllow: /private/open\n"
        with patch("urllib.request.urlopen", return_value=io.BytesIO(robots)) as open_url:
            cache = RobotsCache("crawler-test", timeout=2.5)

            self.assertFalse(cache.allowed("https://jobs.example/private/role"))
            self.assertTrue(cache.allowed("https://jobs.example/public/role"))
            self.assertTrue(cache.allowed("https://jobs.example/private/open/role"))

        open_url.assert_called_once()
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "https://jobs.example/robots.txt")
        self.assertEqual(request.get_header("User-agent"), "crawler-test")
        self.assertEqual(open_url.call_args.kwargs["timeout"], 2.5)

    def test_unavailable_robots_file_fails_open_after_bounded_timeout(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")) as open_url:
            cache = RobotsCache("crawler-test", timeout=1.5)

            self.assertTrue(cache.allowed("https://jobs.example/role"))

        self.assertEqual(open_url.call_args.kwargs["timeout"], 1.5)


if __name__ == "__main__":
    unittest.main()
