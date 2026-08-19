from __future__ import annotations

import unittest
import urllib.request

from tools.safe_http import SameHostHTTPSRedirectHandler, _validate_https_url


class SafeUrlTests(unittest.TestCase):
    def test_https_standard_port_allowed(self):
        self.assertEqual(_validate_https_url("https://example.com/feed.xml"), ("example.com", None))
        self.assertEqual(_validate_https_url("https://example.com:443/feed.xml"), ("example.com", 443))

    def test_http_rejected(self):
        with self.assertRaises(RuntimeError):
            _validate_https_url("http://example.com/feed.xml")

    def test_credentials_rejected(self):
        with self.assertRaises(RuntimeError):
            _validate_https_url("https://user:pass@example.com/feed.xml")

    def test_non_standard_port_rejected(self):
        with self.assertRaises(RuntimeError):
            _validate_https_url("https://example.com:8443/feed.xml")

    def test_fragment_rejected(self):
        with self.assertRaises(RuntimeError):
            _validate_https_url("https://example.com/feed.xml#part")


class RedirectPolicyTests(unittest.TestCase):
    def make_request(self, url: str):
        return urllib.request.Request(url)

    def test_same_host_https_redirect_allowed(self):
        handler = SameHostHTTPSRedirectHandler("example.com")
        req = handler.redirect_request(
            self.make_request("https://example.com/a"),
            None,
            302,
            "Found",
            {},
            "https://example.com/b",
        )
        self.assertEqual(req.full_url, "https://example.com/b")

    def test_cross_host_redirect_blocked(self):
        handler = SameHostHTTPSRedirectHandler("example.com")
        with self.assertRaises(RuntimeError):
            handler.redirect_request(
                self.make_request("https://example.com/a"),
                None,
                302,
                "Found",
                {},
                "https://evil.example.net/b",
            )

    def test_https_to_http_redirect_blocked(self):
        handler = SameHostHTTPSRedirectHandler("example.com")
        with self.assertRaises(RuntimeError):
            handler.redirect_request(
                self.make_request("https://example.com/a"),
                None,
                302,
                "Found",
                {},
                "http://example.com/b",
            )

    def test_redirect_limit_enforced(self):
        handler = SameHostHTTPSRedirectHandler("example.com", max_redirects=1)
        handler.redirect_request(self.make_request("https://example.com/a"), None, 302, "Found", {}, "https://example.com/b")
        with self.assertRaises(RuntimeError):
            handler.redirect_request(self.make_request("https://example.com/b"), None, 302, "Found", {}, "https://example.com/c")


if __name__ == "__main__":
    unittest.main()
