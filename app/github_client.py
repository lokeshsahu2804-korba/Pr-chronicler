"""GitHub Client module.

Phase 3 Implementation:
Asynchronous GitHub client using httpx.AsyncClient to hydrate technical context
from the GitHub REST API for accepted merged pull requests:
- Pull Request details and markdown body
- Changed files with pagination (filename, status, additions, deletions, changes, patch)
- Total diff character count calculation
- Linked issue detection and retrieval (Fixes #..., Closes #..., Resolves #...)
- Graceful error handling (401 auth, 404 not found, 403 rate limit, network errors)
"""

import re
from typing import Any, Optional
import httpx
from app.config import settings
from app.logging_config import logger
from app.models import ChangedFileModel, HydratedPRContext, LinkedIssueModel


class GitHubClientError(Exception):
    """Base exception for GitHub client errors."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GitHubClient:
    """Asynchronous client for interacting with the GitHub REST API."""

    def __init__(
        self,
        token: Optional[str] = None,
        base_url: str = "https://api.github.com",
    ) -> None:
        self.token = token or settings.github_token
        self.base_url = base_url.rstrip("/")

    def _get_headers(self) -> dict[str, str]:
        """Construct standard GitHub REST API headers."""
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "PR-Chronicler-App/0.1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token and self.token.strip():
            headers["Authorization"] = f"Bearer {self.token.strip()}"
        return headers

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> httpx.Response:
        """Perform an HTTP request with error handling and logging."""
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        try:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                timeout=15.0,
            )
        except httpx.RequestError as exc:
            logger.error(
                "GitHub API network error during %s %s: %s",
                method,
                url,
                type(exc).__name__,
            )
            raise GitHubClientError(
                f"Network error during GitHub API request: {type(exc).__name__}"
            ) from exc

        # Log GitHub endpoint and HTTP status
        logger.info("GitHub API request: %s %s -> HTTP %d", method, url, response.status_code)

        if response.status_code == 401:
            logger.error(
                "GitHub API authentication failed (HTTP 401) on %s. Please verify GITHUB_TOKEN.",
                endpoint,
            )
            raise GitHubClientError("GitHub API authentication failure (HTTP 401)", status_code=401)

        if response.status_code == 403:
            remaining = response.headers.get("x-ratelimit-remaining")
            if remaining == "0":
                reset_time = response.headers.get("x-ratelimit-reset", "unknown")
                logger.error(
                    "GitHub API rate limit exceeded (HTTP 403) on %s. Rate limit resets at: %s",
                    endpoint,
                    reset_time,
                )
                raise GitHubClientError("GitHub API rate limit exceeded (HTTP 403)", status_code=403)
            logger.error("GitHub API access forbidden (HTTP 403) on %s.", endpoint)
            raise GitHubClientError("GitHub API access forbidden (HTTP 403)", status_code=403)

        if response.status_code == 404:
            logger.warning("GitHub API resource not found (HTTP 404) on %s.", endpoint)
            raise GitHubClientError(
                f"GitHub API resource not found (HTTP 404) on {endpoint}",
                status_code=404,
            )

        if response.status_code >= 400:
            logger.error("GitHub API error HTTP %d on %s", response.status_code, endpoint)
            raise GitHubClientError(
                f"GitHub API returned HTTP {response.status_code}",
                status_code=response.status_code,
            )

        return response

    async def get_pull_request(
        self,
        client: httpx.AsyncClient,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> dict[str, Any]:
        """Fetch pull request metadata from GET /repos/{owner}/{repo}/pulls/{pull_number}."""
        endpoint = f"/repos/{owner}/{repo}/pulls/{pull_number}"
        response = await self._request(client, "GET", endpoint)
        return response.json()

    async def get_pull_request_files(
        self,
        client: httpx.AsyncClient,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> list[ChangedFileModel]:
        """Fetch all changed files with pagination from GET /repos/{owner}/{repo}/pulls/{pull_number}/files."""
        changed_files: list[ChangedFileModel] = []
        page = 1
        per_page = 100

        while True:
            endpoint = f"/repos/{owner}/{repo}/pulls/{pull_number}/files"
            params = {"page": page, "per_page": per_page}
            response = await self._request(client, "GET", endpoint, params=params)
            data = response.json()

            if not isinstance(data, list):
                logger.error(
                    "Malformed GitHub response for PR files: expected list, got %s",
                    type(data),
                )
                break

            for item in data:
                patch = item.get("patch")  # Handled explicitly: may be None for binary or large diffs
                additions = item.get("additions", 0)
                deletions = item.get("deletions", 0)
                changes = item.get("changes", additions + deletions)
                changed_files.append(
                    ChangedFileModel(
                        filename=item.get("filename", "unknown"),
                        status=item.get("status", "modified"),
                        additions=additions,
                        deletions=deletions,
                        changes=changes,
                        patch=patch,
                    )
                )

            # Follow GitHub Link header rel="next" pagination or check page size
            link_header = response.headers.get("link", "")
            if 'rel="next"' in link_header:
                page += 1
            elif len(data) == per_page:
                page += 1
            else:
                break

        return changed_files

    @staticmethod
    def detect_linked_issue_numbers(pr_body: Optional[str]) -> list[int]:
        """Detect issue reference numbers in PR body (e.g. Fixes #12, Closes #12, Resolves #12)."""
        if not pr_body:
            return []
        pattern = re.compile(r'(?i)\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s+#(\d+)\b')
        matches = pattern.findall(pr_body)
        # Deduplicate while preserving discovery order
        return [int(num) for num in dict.fromkeys(matches)]

    async def get_issue(
        self,
        client: httpx.AsyncClient,
        owner: str,
        repo: str,
        issue_number: int,
    ) -> Optional[LinkedIssueModel]:
        """Fetch issue details from GET /repos/{owner}/{repo}/issues/{issue_number}."""
        endpoint = f"/repos/{owner}/{repo}/issues/{issue_number}"
        try:
            response = await self._request(client, "GET", endpoint)
            data = response.json()
            author = (
                data.get("user", {}).get("login", "unknown")
                if isinstance(data.get("user"), dict)
                else "unknown"
            )
            return LinkedIssueModel(
                number=data.get("number", issue_number),
                title=data.get("title", f"Issue #{issue_number}"),
                body=data.get("body"),
                state=data.get("state", "unknown"),
                author=author,
            )
        except GitHubClientError as exc:
            logger.warning(
                "Could not retrieve linked issue #%d from %s: %s",
                issue_number,
                endpoint,
                exc,
            )
            return None
        except Exception as exc:
            logger.warning(
                "Unexpected error retrieving linked issue #%d from %s: %s",
                issue_number,
                endpoint,
                type(exc).__name__,
            )
            return None

    async def hydrate_pr_context(
        self,
        repo_full_name: str,
        pr_number: int,
        fallback_title: Optional[str] = None,
        fallback_author: Optional[str] = None,
        fallback_body: Optional[str] = None,
    ) -> HydratedPRContext:
        """Hydrate complete technical context for an accepted merged PR."""
        parts = repo_full_name.split("/", 1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            raise GitHubClientError(f"Invalid repository full name format: '{repo_full_name}'")

        owner, repo = parts[0].strip(), parts[1].strip()

        async with httpx.AsyncClient() as client:
            # 1. Fetch Pull Request details (for definitive body, title, author)
            pr_data: dict[str, Any] = {}
            try:
                pr_data = await self.get_pull_request(client, owner, repo, pr_number)
            except GitHubClientError as exc:
                logger.error(
                    "Failed to fetch PR #%d metadata for %s: %s",
                    pr_number,
                    repo_full_name,
                    exc,
                )
                raise

            title = pr_data.get("title") or fallback_title or "Untitled"
            body = pr_data.get("body") if pr_data.get("body") is not None else fallback_body
            author = (
                pr_data.get("user", {}).get("login")
                if isinstance(pr_data.get("user"), dict)
                else fallback_author or "unknown"
            )

            # 2. Fetch changed files across all pages
            changed_files = await self.get_pull_request_files(client, owner, repo, pr_number)

            # 3. Calculate total diff character count
            diff_characters = sum(len(f.patch) for f in changed_files if f.patch)
            logger.info("GitHub PR diff character count: %d", diff_characters)

            # 4. Detect and hydrate linked issues
            issue_numbers = self.detect_linked_issue_numbers(body)
            linked_issues: list[LinkedIssueModel] = []

            if issue_numbers:
                logger.info(
                    "Detected %d linked issue reference(s) in PR body: %s",
                    len(issue_numbers),
                    issue_numbers,
                )
                for num in issue_numbers:
                    issue_model = await self.get_issue(client, owner, repo, num)
                    if issue_model:
                        linked_issues.append(issue_model)
            else:
                logger.info("No linked issue references found in PR body.")

            has_linked = len(linked_issues) > 0

            # 5. Log summary of successful hydration
            logger.info(
                "Hydration complete for %s #%d: %d changed files, %d diff characters, linked issue found: %s",
                repo_full_name,
                pr_number,
                len(changed_files),
                diff_characters,
                has_linked,
            )

            return HydratedPRContext(
                repository=repo_full_name,
                pr_number=pr_number,
                title=title,
                author=author,
                body=body,
                changed_files=changed_files,
                diff_characters=diff_characters,
                linked_issues=linked_issues,
                has_linked_issue=has_linked,
            )


# Default singleton client instance
github_client = GitHubClient()
