"""Subversion working-copy adapter -- no PR API, so `fetch_prs` always
returns an empty page. Exists so callers that iterate over `PlatformClient`
subclasses (e.g. eval-kit's `--platform svn` mode) have one to construct."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional

from .base import PlatformClient


class SvnClient(PlatformClient):
    """Subversion working-copy adapter (no PR API; fetch_prs returns empty nodes)."""

    def __init__(
        self,
        owner: str,
        repo_name: str,
        token: Optional[str] = None,
        svn_url: str = "",
        svn_username: Optional[str] = None,
    ):
        super().__init__(owner, repo_name, token)
        self.svn_url = svn_url or ""
        self.svn_username = svn_username

    def fetch_prs(
        self,
        cursor: Optional[str] = None,
        page_size: int = 50,
        start_date: Optional[datetime] = None,
    ) -> dict:
        return {
            "data": {
                "repository": {
                    "primaryLanguage": {"name": None},
                    "owner": {"login": self.owner},
                    "name": self.repo_name,
                    "pullRequests": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [],
                    },
                }
            }
        }

    def fetch_issue(self, issue_number: int) -> Optional[dict]:
        return None

    def get_repo_url(self, include_token: bool = False) -> str:
        return self.svn_url

    def extract_issue_number_from_text(self, text: str) -> List[int]:
        if not text:
            return []
        nums = [int(m) for m in re.findall(r"#(\d+)", text)]
        return list(set(nums))

    def fetch_repo_languages(self) -> Optional[Dict[str, int]]:
        return None

    def fetch_issue_count(self) -> dict:
        return {"open": 0, "closed": 0, "total": 0}

    def fetch_patch(self, base_commit: str, head_commit: str) -> Optional[str]:
        return None
