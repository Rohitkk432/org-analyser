#!/usr/bin/env python3
"""Smoke tests for platforms.bitbucket.BitbucketClient auth."""

from __future__ import annotations

import sys
import unittest

from platforms.bitbucket import BitbucketClient
from platforms.errors import PlatformAuthError


class TestBitbucketClientAuth(unittest.TestCase):
    def test_access_token_uses_bearer(self):
        # No username + non-ATATT token → workspace/repo access token → Bearer.
        client = BitbucketClient("owner", "repo", token="secret")
        self.assertIsNone(client.session.auth)
        self.assertEqual(client.session.headers["Authorization"], "Bearer secret")

    def test_api_token_without_email_raises(self):
        # ATATT API token needs the Atlassian email; static user fails on REST.
        with self.assertRaises(PlatformAuthError):
            BitbucketClient("owner", "repo", token="ATATTsecret")

    def test_uses_basic_auth_when_username_provided(self):
        client = BitbucketClient("owner", "repo", token="secret", username="bob")
        self.assertEqual(client.session.auth, ("bob", "secret"))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
