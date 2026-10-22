"""Main FastAPI application entry point.

Initializes the FastAPI application, configures lifecycle events (logging setup),
and defines foundational endpoints including GET /health.
"""

import hashlib
import hmac
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional
from fastapi import FastAPI, Header, HTTPException, Request, status
from app.config import settings
from app.email_dispatcher import email_dispatcher
from app.github_client import GitHubClientError, github_client
from app.llm_chain import LLMChainError, pr_chronicler_chain
from app.logging_config import logger, setup_logging
from app.models import GitHubWebhookPayload, HealthResponse, WebhookResponse

# In-memory delivery tracking for lightweight webhook idempotency (Requirement 9)
_PROCESSED_DELIVERIES: set[str] = set()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager to handle startup and shutdown routines."""
    setup_logging()
    logger.info("Initializing PR Chronicler & Learning Dispatcher...")
    logger.info("Configuration loaded: env=%s, port=%d", settings.app_env, settings.app_port)
    yield
    logger.info("Shutting down PR Chronicler & Learning Dispatcher...")


app = FastAPI(
    title="Automated Open-Source PR Chronicler and Learning Dispatcher",
    description="Captures merged PR events, generates AI architectural insights, and dispatches learning summaries.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> dict[str, str]:
    """Health check endpoint to verify backend operational readiness.

    Returns:
        JSON response with status: "ok"
    """
    logger.info("Health check endpoint accessed.")
    return {"status": "ok"}


@app.post(
    "/webhook/github",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    tags=["Webhook"],
)
async def github_webhook(
    request: Request,
    payload: GitHubWebhookPayload,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    x_github_delivery: Optional[str] = Header(None, alias="X-GitHub-Delivery"),
) -> WebhookResponse:
    """Ingest GitHub pull_request webhook events and hydrate accepted merged PRs.

    Requirements:
    - Extracts: action, repository full name, PR number, PR title, PR author, pull_request.merged
    - Validates X-Hub-Signature-256 HMAC when GITHUB_WEBHOOK_SECRET is configured
    - Ensures lightweight idempotency via X-GitHub-Delivery tracking
    - Accepts event ONLY when: action == 'closed' AND pull_request.merged == true
    - For all other events: returns HTTP 200, logs ignored reason, stops processing.
    - For accepted PRs: retrieves technical context via GitHub API hydration (files, patches, linked issues).
    - Measures and logs end-to-end processing latency.
    """
    start_time = time.perf_counter()

    # 1. Webhook Authenticity Verification (Requirement 8)
    webhook_secret = settings.github_webhook_secret
    if webhook_secret and webhook_secret.strip() and request is not None:
        raw_body = await request.body()
        if not (x_hub_signature_256 and isinstance(x_hub_signature_256, str)):
            logger.warning("Rejecting webhook: Missing X-Hub-Signature-256 header while secret configured.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-Hub-Signature-256 header",
            )
        expected_sig = "sha256=" + hmac.new(
            webhook_secret.strip().encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(x_hub_signature_256, expected_sig):
            logger.warning("Rejecting webhook: Invalid X-Hub-Signature-256 HMAC signature.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )
    else:
        logger.debug("GITHUB_WEBHOOK_SECRET not configured; signature verification bypassed.")

    # 2. Extract metadata
    action = (payload.action or "unknown").strip().lower()
    repo_name = (
        payload.repository.full_name
        if (payload.repository and payload.repository.full_name)
        else "unknown/repository"
    )
    pr_number = payload.number or (payload.pull_request.number if payload.pull_request else None) or 0
    pr_title = (
        payload.pull_request.title
        if (payload.pull_request and payload.pull_request.title)
        else "Untitled"
    )
    author = (
        payload.pull_request.user.login
        if (payload.pull_request and payload.pull_request.user and payload.pull_request.user.login)
        else "unknown"
    )
    is_merged = bool(payload.pull_request and payload.pull_request.merged)
    fallback_body = payload.pull_request.body if payload.pull_request else ""

    # 3. Lightweight In-Memory Idempotency Check (Requirement 9)
    if x_github_delivery and isinstance(x_github_delivery, str):
        if x_github_delivery in _PROCESSED_DELIVERIES:
            logger.info("Duplicate webhook delivery %s detected. Idempotent ignore.", x_github_delivery)
            return WebhookResponse(
                status="ignored",
                reason=f"Duplicate delivery {x_github_delivery} already processed",
                action=action,
                repository=repo_name,
                pr_number=pr_number,
                title=pr_title,
                author=author,
                merged=is_merged,
            )
        if len(_PROCESSED_DELIVERIES) > 1000:
            _PROCESSED_DELIVERIES.clear()
        _PROCESSED_DELIVERIES.add(x_github_delivery)

    # Standardized extraction log
    logger.info(
        "Webhook received\n"
        "Action: %s\n"
        "Repository: %s\n"
        "PR: #%s\n"
        "Title: %s\n"
        "Author: %s\n"
        "Merged: %s",
        action,
        repo_name,
        pr_number,
        pr_title,
        author,
        "true" if is_merged else "false",
    )

    # Filtering logic: Both action == 'closed' AND is_merged == True are required
    if action != "closed":
        reason = "action is not closed"
        logger.info("Event ignored: %s", reason)
        return WebhookResponse(
            status="ignored",
            reason=reason,
            action=action,
            repository=repo_name,
            pr_number=pr_number,
            title=pr_title,
            author=author,
            merged=is_merged,
        )

    if not is_merged:
        reason = "pull request was closed but not merged"
        logger.info("Event ignored: %s", reason)
        return WebhookResponse(
            status="ignored",
            reason=reason,
            action=action,
            repository=repo_name,
            pr_number=pr_number,
            title=pr_title,
            author=author,
            merged=is_merged,
        )

    # Event Accepted -> Hydrate via GitHub REST API
    logger.info("Event accepted: merged PR")

    try:
        context = await github_client.hydrate_pr_context(
            repo_full_name=repo_name,
            pr_number=pr_number,
            fallback_title=pr_title,
            fallback_author=author,
            fallback_body=fallback_body,
        )
        # Phase 4: LangChain LCEL + Gemini Technical Reflection
        reflection = None
        try:
            reflection = await pr_chronicler_chain.generate_reflection(context)
        except LLMChainError as exc:
            latency = round(time.perf_counter() - start_time, 2)
            logger.warning(
                "LLM reflection synthesis was not completed for %s #%d: %s (latency: %.2fs)",
                repo_name,
                pr_number,
                exc,
                latency,
            )
            return WebhookResponse(
                status="accepted",
                repository=context.repository,
                pr_number=context.pr_number,
                title=context.title,
                author=context.author,
                changed_files=len(context.changed_files),
                diff_characters=context.diff_characters,
                linked_issue=context.has_linked_issue,
                reflection=None,
                reason=f"Hydration succeeded, but LLM synthesis failed: {exc}",
                action=action,
                merged=True,
                latency_seconds=latency,
            )

        # Phase 5: SMTP Email Dispatch
        email_dispatched = False
        try:
            email_dispatched = await email_dispatcher.send_reflection_email(
                reflection=reflection,
                repository=context.repository,
                pr_number=context.pr_number,
            )
        except Exception as exc:
            logger.error(
                "SMTP dispatch failed unexpectedly for %s #%d: %s",
                repo_name,
                pr_number,
                type(exc).__name__,
            )

        latency = round(time.perf_counter() - start_time, 2)
        logger.info(
            "Processing completed for %s #%d in %.2f seconds",
            repo_name,
            pr_number,
            latency,
        )

        return WebhookResponse(
            status="accepted",
            repository=context.repository,
            pr_number=context.pr_number,
            title=context.title,
            author=context.author,
            changed_files=len(context.changed_files),
            diff_characters=context.diff_characters,
            linked_issue=context.has_linked_issue,
            reflection=reflection,
            email_dispatched=email_dispatched,
            action=action,
            merged=True,
            latency_seconds=latency,
        )
    except GitHubClientError as exc:
        latency = round(time.perf_counter() - start_time, 2)
        logger.error("GitHub API hydration failed for %s #%d: %s", repo_name, pr_number, exc)
        return WebhookResponse(
            status="error",
            reason=f"GitHub API hydration failed: {exc}",
            repository=repo_name,
            pr_number=pr_number,
            action=action,
            merged=True,
            latency_seconds=latency,
        )
    except Exception as exc:
        latency = round(time.perf_counter() - start_time, 2)
        logger.error("Unexpected error during hydration for %s #%d: %s", repo_name, pr_number, type(exc).__name__)
        return WebhookResponse(
            status="error",
            reason=f"Unexpected hydration failure: {type(exc).__name__}",
            repository=repo_name,
            pr_number=pr_number,
            action=action,
            merged=True,
            latency_seconds=latency,
        )


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    """Root endpoint providing service metadata and discovery links."""
    return {
        "service": "Automated Open-Source PR Chronicler and Learning Dispatcher",
        "phase": "Phase 5 - SMTP Email Dispatch",
        "health": "/health",
        "webhook": "/webhook/github",
        "docs": "/docs",
    }
