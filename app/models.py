"""Data models for PR Chronicler.

Defines Pydantic schemas for request validation, response serialization, and
future domain models.
"""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class HealthResponse(BaseModel):
    """Health check endpoint response schema."""

    status: str = Field(default="ok", description="Application operational status")


# ------------------------------------------------------------------------------
# Phase 2: GitHub Webhook Data Models
# ------------------------------------------------------------------------------


class GitHubUser(BaseModel):
    """GitHub user representation."""

    model_config = ConfigDict(extra="ignore")

    login: str = Field(default="unknown", description="GitHub user login handle")


class GitHubPullRequest(BaseModel):
    """GitHub pull request schema."""

    model_config = ConfigDict(extra="ignore")

    number: Optional[int] = Field(default=None, description="Pull Request number")
    title: Optional[str] = Field(default="Untitled", description="Pull Request title")
    body: Optional[str] = Field(default="", description="Pull Request markdown body")
    user: Optional[GitHubUser] = Field(default=None, description="PR author")
    merged: Optional[bool] = Field(default=False, description="Whether the PR is merged")


class GitHubRepository(BaseModel):
    """GitHub repository schema."""

    model_config = ConfigDict(extra="ignore")

    full_name: Optional[str] = Field(
        default="unknown/repository",
        description="Full repository name in owner/repo format",
    )


class GitHubWebhookPayload(BaseModel):
    """Parsed GitHub webhook event payload for pull_request events."""

    model_config = ConfigDict(extra="ignore")

    action: Optional[str] = Field(
        default=None,
        description="Webhook action (e.g. 'opened', 'closed', 'synchronize', 'reopened')",
    )
    number: Optional[int] = Field(
        default=None,
        description="Pull request number from root payload",
    )
    pull_request: Optional[GitHubPullRequest] = Field(
        default=None,
        description="Embedded pull request details",
    )
    repository: Optional[GitHubRepository] = Field(
        default=None,
        description="Target repository details",
    )


# ------------------------------------------------------------------------------
# Phase 3: Hydrated PR Context Models
# ------------------------------------------------------------------------------


class ChangedFileModel(BaseModel):
    """Details for a single file modified in a pull request."""

    model_config = ConfigDict(extra="ignore")

    filename: str = Field(description="Relative path of the changed file")
    status: str = Field(default="modified", description="Git status (modified, added, removed, etc.)")
    additions: int = Field(default=0, description="Lines added")
    deletions: int = Field(default=0, description="Lines deleted")
    changes: int = Field(default=0, description="Total changes")
    patch: Optional[str] = Field(default=None, description="Raw unidiff patch content if available")


class LinkedIssueModel(BaseModel):
    """Details for an issue linked to the pull request."""

    model_config = ConfigDict(extra="ignore")

    number: int = Field(description="Issue number")
    title: str = Field(description="Issue title")
    body: Optional[str] = Field(default=None, description="Issue body text")
    state: str = Field(default="unknown", description="Issue state (open, closed)")
    author: str = Field(default="unknown", description="Issue author handle")


class HydratedPRContext(BaseModel):
    """Structured technical context hydrated from the GitHub API."""

    model_config = ConfigDict(extra="ignore")

    repository: str = Field(description="Repository full name (owner/repo)")
    pr_number: int = Field(description="Pull request number")
    title: str = Field(description="PR title")
    author: str = Field(description="PR author login")
    body: Optional[str] = Field(default="", description="PR body content")
    changed_files: list[ChangedFileModel] = Field(default_factory=list, description="List of files changed")
    diff_characters: int = Field(default=0, description="Total character count of all patches")
    linked_issues: list[LinkedIssueModel] = Field(default_factory=list, description="Hydrated linked issues")
    has_linked_issue: bool = Field(default=False, description="Flag indicating if linked issues were found")


class PRReflection(BaseModel):
    """Structured technical reflection about a merged pull request.

    Designed for LangChain LCEL synthesis with Gemini and JsonOutputParser.
    """

    model_config = ConfigDict(extra="ignore")

    issue_details: str = Field(
        ...,
        description="Concise explanation of the root cause of the bug OR the feature requirement.",
    )
    execution_summary: str = Field(
        ...,
        description="Evidence-based description of what was actually implemented, grounded in the PR changes.",
    )
    key_learnings: list[str] = Field(
        ...,
        description="Concrete technical learnings grounded in the PR changes (minimum 3, maximum 4).",
    )

    @field_validator("key_learnings")
    @classmethod
    def validate_key_learnings_count(cls, v: list[str]) -> list[str]:
        """Enforce strict 3 to 4 key learnings requirement."""
        if not (3 <= len(v) <= 4):
            raise ValueError(
                f"key_learnings must contain between 3 and 4 items, received {len(v)}"
            )
        return v


class WebhookResponse(BaseModel):
    """Unified response schema for GitHub webhook ingestion, hydration, and reflection."""

    model_config = ConfigDict(extra="ignore")

    status: str = Field(description="Processing status: 'accepted', 'ignored', or 'error'")
    repository: Optional[str] = Field(default=None, description="Repository full name")
    pr_number: Optional[int] = Field(default=None, description="Pull request number")
    title: Optional[str] = Field(default=None, description="Pull request title")
    author: Optional[str] = Field(default=None, description="PR author login")
    changed_files: Optional[int] = Field(default=None, description="Count of changed files")
    diff_characters: Optional[int] = Field(default=None, description="Total diff character count")
    linked_issue: Optional[bool] = Field(default=None, description="Whether linked issue exists")
    reflection: Optional[PRReflection] = Field(default=None, description="Synthesized technical reflection")
    email_dispatched: Optional[bool] = Field(default=None, description="Whether email dispatch succeeded")
    reason: Optional[str] = Field(default=None, description="Details when ignored or on error")
    action: Optional[str] = Field(default=None, description="Webhook action parsed")
    merged: Optional[bool] = Field(default=None, description="PR merged flag")
    latency_seconds: Optional[float] = Field(default=None, description="End-to-end processing latency in seconds")


# Alias for backward compatibility
WebhookFilterResponse = WebhookResponse


# ------------------------------------------------------------------------------
# Phase 5 Stubs: Email Dispatch Models
# ------------------------------------------------------------------------------


class LearningDispatchStub(BaseModel):
    """Stub schema for educational takeaways generated for email dispatch."""

    pr_title: Optional[str] = None
    pr_url: Optional[str] = None
    summary: Optional[str] = None
    takeaways: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
