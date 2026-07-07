#!/usr/bin/env python3
"""Smoke tests for Bitbucket support in run_all_repos.py and platform_clients.py."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

import requests

from platform_clients import BitbucketClient
from run_all_repos import (
    BitbucketAPI,
    _bitbucket_to_repo_info,
    _should_include,
    discover_bitbucket_repos,
)


SAMPLE_REPO = {
    "uuid": "{abc}",
    "full_name": "my-workspace/backend-api",
    "slug": "backend-api",
    "name": "backend-api",
    "workspace": {"slug": "my-workspace"},
    "is_private": True,
    "is_archived": False,
    "parent": None,
    "mainbranch": {"name": "main"},
    "language": "python",
}


class TestBitbucketMapper(unittest.TestCase):
    def test_bitbucket_to_repo_info(self):
        ri = _bitbucket_to_repo_info(SAMPLE_REPO, "my-workspace")
        self.assertEqual(ri.full_name, "my-workspace/backend-api")
        self.assertEqual(ri.owner, "my-workspace")
        self.assertEqual(ri.name, "backend-api")
        self.assertTrue(ri.private)
        self.assertFalse(ri.archived)
        self.assertFalse(ri.fork)
        self.assertEqual(ri.default_branch, "main")
        self.assertEqual(ri.language, "python")
        self.assertEqual(ri.platform, "bitbucket")

    def test_fork_detection(self):
        forked = {**SAMPLE_REPO, "parent": {"full_name": "other/repo"}}
        ri = _bitbucket_to_repo_info(forked, "my-workspace")
        self.assertTrue(ri.fork)

    def test_filters(self):
        ri = _bitbucket_to_repo_info(SAMPLE_REPO, "my-workspace")
        self.assertTrue(_should_include(ri, "all", False, False, set()))
        self.assertFalse(_should_include(ri, "public", False, False, set()))
        self.assertTrue(_should_include(ri, "private", False, False, set()))


class TestBitbucketDiscovery(unittest.TestCase):
    def test_discover_bitbucket_repos(self):
        api = MagicMock(spec=BitbucketAPI)
        api.list_workspaces.return_value = [{"slug": "team-a"}, {"slug": "team-b"}]
        api.list_workspace_repos.side_effect = lambda ws: (
            [SAMPLE_REPO] if ws == "team-a" else []
        )
        api.list_user_repos.return_value = []

        result = discover_bitbucket_repos(api, only_workspaces=["team-a"])
        self.assertIn("team-a", result)
        self.assertEqual(len(result["team-a"]), 1)
        self.assertEqual(result["team-a"][0].full_name, "my-workspace/backend-api")


class TestBitbucketPagination(unittest.TestCase):
    def test_paginate_follows_next_links(self):
        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = {
            "values": [{"slug": "repo-1"}],
            "next": "https://api.bitbucket.org/2.0/repositories/ws?page=2",
        }
        page2 = MagicMock()
        page2.status_code = 200
        page2.json.return_value = {
            "values": [{"slug": "repo-2"}],
            "next": None,
        }

        api = BitbucketAPI("dummy")
        with patch.object(api.session, "request", side_effect=[page1, page2]) as mock_req:
            results = api._paginate("https://api.bitbucket.org/2.0/repositories/ws")
        self.assertEqual([r["slug"] for r in results], ["repo-1", "repo-2"])
        self.assertEqual(mock_req.call_count, 2)


class TestBitbucketAuth(unittest.TestCase):
    def test_basic_auth_when_username_provided(self):
        api = BitbucketAPI("secret-token", username="alice@example.com")
        api._apply_basic("alice@example.com")
        self.assertEqual(api.session.auth, ("alice@example.com", "secret-token"))

    def test_authenticate_tries_bearer_then_basic(self):
        api = BitbucketAPI("secret-token")
        bearer_resp = MagicMock(status_code=401)
        bearer_resp.raise_for_status.side_effect = requests.HTTPError(response=bearer_resp)
        ok_resp = MagicMock(status_code=200)
        ok_resp.raise_for_status.return_value = None
        ok_resp.json.return_value = {"username": "alice"}

        with patch.object(api, "_request", side_effect=[bearer_resp, ok_resp]):
            user = api.authenticate()
        self.assertEqual(user["username"], "alice")
        self.assertTrue(api._auth_mode.startswith("basic:"))


class TestBitbucketClientAuth(unittest.TestCase):
    def test_uses_basic_auth_by_default(self):
        client = BitbucketClient("owner", "repo", token="secret")
        self.assertEqual(client.session.auth, ("x-bitbucket-api-token-auth", "secret"))

    def test_uses_username_when_provided(self):
        client = BitbucketClient("owner", "repo", token="secret", username="bob")
        self.assertEqual(client.session.auth, ("bob", "secret"))


class TestLivePublicApi(unittest.TestCase):
    """Optional live checks against Bitbucket's public API (no token needed)."""

    def test_public_workspace_repo_shape(self):
        resp = requests.get(
            "https://api.bitbucket.org/2.0/repositories/atlassian",
            params={"pagelen": 1},
            timeout=30,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("values", data)
        self.assertTrue(data["values"])
        ri = _bitbucket_to_repo_info(data["values"][0], "atlassian")
        self.assertEqual(ri.platform, "bitbucket")
        self.assertTrue(ri.full_name.startswith("atlassian/"))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
