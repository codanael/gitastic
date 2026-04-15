"""Azure DevOps REST API client for commit ingestion."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

PAGE_SIZE = 100
MAX_RETRIES = 3
BACKOFF_BASE = 2  # seconds


class AzureDevOpsClient:
    def __init__(self, organization: str, pat: str, base_url: str = "https://dev.azure.com") -> None:
        self._base_url = f"{base_url.rstrip('/')}/{organization}"
        self._session = requests.Session()
        self._session.auth = ("", pat)
        self._session.headers["Accept"] = "application/json"

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET with retry + exponential backoff for rate limiting."""
        for attempt in range(MAX_RETRIES):
            resp = self._session.get(url, params=params)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", BACKOFF_BASE**attempt))
                logger.warning("Rate limited, retrying in %ds", retry_after)
                time.sleep(retry_after)
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return resp.json()  # unreachable but satisfies type checker

    def list_repositories(self, project: str) -> list[dict[str, Any]]:
        """List all git repositories for a project."""
        url = f"{self._base_url}/{project}/_apis/git/repositories"
        data = self._get(url, params={"api-version": "7.1"})
        return data.get("value", [])

    def get_commits(
        self,
        project: str,
        repo_id: str,
        from_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all commits for a repo since from_date, handling pagination."""
        url = f"{self._base_url}/{project}/_apis/git/repositories/{repo_id}/commits"
        all_commits: list[dict[str, Any]] = []
        skip = 0

        while True:
            params: dict[str, Any] = {
                "api-version": "7.1",
                "$top": PAGE_SIZE,
                "$skip": skip,
            }
            if from_date:
                params["searchCriteria.fromDate"] = from_date

            data = self._get(url, params=params)
            commits = data.get("value", [])
            if not commits:
                break

            all_commits.extend(commits)
            if len(commits) < PAGE_SIZE:
                break
            skip += PAGE_SIZE

        return all_commits
