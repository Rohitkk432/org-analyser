"""Offline adapter for local directories (git, svn, or plain folders) -- no
network calls at all, so eval-kit's `--platform local` mode still works with
no token and no connectivity."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional

from .base import PlatformClient


class LocalClient(PlatformClient):
    """Offline adapter for local directories (git, svn, or plain folders)."""

    def __init__(self, owner: str, repo_name: str, repo_path: str = ""):
        super().__init__(owner, repo_name, token=None)
        self.repo_path = repo_path

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
        return self.repo_path

    def extract_issue_number_from_text(self, text: str) -> List[int]:
        if not text:
            return []
        return list(set(int(m) for m in re.findall(r"#(\d+)", text)))

    def fetch_repo_languages(self) -> Optional[Dict[str, int]]:
        return None

    def fetch_issue_count(self) -> dict:
        return {"open": 0, "closed": 0, "total": 0}

    def fetch_patch(self, base_commit: str, head_commit: str) -> Optional[str]:
        return None
