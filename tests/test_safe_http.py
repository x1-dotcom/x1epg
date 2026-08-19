from __future__ import annotations

import unittest
import urllib.request

from tools.safe_http import SameHostHTTPSRedirectHandler, _is_public_ip, _validate_https_url


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

    def test_localhost_rejected(self):
        for url in ("https://localhost/feed", "https://api.localhost/feed", "https://service.local/feed"):
            with self.subTest(url=url):
                with self.assertRaises(RuntimeError):
                    _validate_https_url(url)

    def test_private_ip_literals_rejected(self):
        for url in (
            "https://127.0.0.1/feed",
            "https://10.0.0.1/feed",
            "https://192.168.1.10/feed",
            "https://169.254.169.254/latest/meta-data",
            "https://[::1]/feed",
        ):
            with self.subTest(url=url):
                with self.assertRaises(RuntimeError):
                    _validate_https_url(url)

    def test_public_ip_classifier(self):
        self.assertTrue(_is_public_ip("8.8.8.8"))
        self.assertFalse(_is_public_ip("127.0.0.1"))
        self.assertFalse(_is_public_ip("10.0.0.1"))
        self.assertFalse(_is_public_ip("169.254.169.254"))


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

    def test_redirect_to_private_ip_blocked(self):
        handler = SameHostHTTPSRedirectHandler("example.com")
        with self.assertRaises(RuntimeError):
            handler.redirect_request(
                self.make_request("https://example.com/a"),
                None,
                302,
                "Found",
                {},
                "https://127.0.0.1/b",
            )

    def test_redirect_limit_enforced(self):
        handler = SameHostHTTPSRedirectHandler("example.com", max_redirects=1)
        handler.redirect_request(self.make_request("https://example.com/a"), None, 302, "Found", {}, "https://example.com/b")
        with self.assertRaises(RuntimeError):
            handler.redirect_request(self.make_request("https://example.com/b"), None, 302, "Found", {}, "https://example.com/c")


if __name__ == "__main__":
    unittest.main()
