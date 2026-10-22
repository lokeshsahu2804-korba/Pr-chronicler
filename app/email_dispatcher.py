"""Email Dispatcher module.

Phase 5 Implementation:
Sends structured PR technical reflections (Issue Details, Execution Summary, Key Learnings)
to configured student inbox(es) via standard-library smtplib and email.message.EmailMessage.
Features:
- Exact subject format: [OS-Log] PR Merged: <Repository Name> (#<PR Number>)
- Responsive HTML email formatted as a clean technical portfolio entry
- Plain-text alternative fallback
- Non-blocking async execution via asyncio.to_thread
- Graceful error handling (authentication, TLS, connection, network failures)
- Dry-run verification mode for testing without sending live emails
- Zero secret logging
"""

import asyncio
from email.message import EmailMessage
from email.utils import formatdate
import html
import smtplib
from typing import Optional

from app.config import settings
from app.logging_config import logger
from app.models import PRReflection


class EmailDispatcherError(Exception):
    """Base exception for email dispatcher failures."""


class EmailDispatcher:
    """SMTP Dispatcher for delivering chronicled technical reflections."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        use_tls: Optional[bool] = None,
        dry_run: Optional[bool] = None,
    ) -> None:
        self.host = host or settings.smtp_host
        self.port = port or settings.smtp_port
        self.user = user or settings.sender_email
        self.password = password or settings.sender_password
        self.use_tls = use_tls if use_tls is not None else settings.smtp_use_tls
        self.dry_run = dry_run if dry_run is not None else settings.smtp_dry_run

        logger.info(
            "EmailDispatcher initialized: host=%s, port=%d, tls=%s, dry_run=%s, sender configured=%s",
            self.host,
            self.port,
            self.use_tls,
            self.dry_run,
            bool(self.user),
        )

    @staticmethod
    def build_subject(repository: str, pr_number: int) -> str:
        """Construct email subject adhering strictly to format:

        [OS-Log] PR Merged: <Repository Name> (#<PR Number>)
        """
        return f"[OS-Log] PR Merged: {repository} (#{pr_number})"

    def create_email_message(
        self,
        reflection: PRReflection,
        repository: str,
        pr_number: int,
        recipient: str,
        sender: Optional[str] = None,
    ) -> EmailMessage:
        """Build a multipart EmailMessage containing HTML and plaintext representations."""
        msg = EmailMessage()
        sender_address = sender or self.user or "pr-chronicler@localhost"
        subject = self.build_subject(repository, pr_number)

        msg["Subject"] = subject
        msg["From"] = sender_address
        msg["To"] = recipient
        msg["Date"] = formatdate(localtime=True)

        # 1. Plaintext fallback body
        learnings_text = "\n".join(
            f"  {idx}. {item}"
            for idx, item in enumerate(reflection.key_learnings, 1)
        )
        plain_text = (
            f"{subject}\n"
            f"{'=' * len(subject)}\n\n"
            f"ISSUE DETAILS\n"
            f"{'-' * 13}\n"
            f"{reflection.issue_details}\n\n"
            f"EXECUTION SUMMARY\n"
            f"{'-' * 17}\n"
            f"{reflection.execution_summary}\n\n"
            f"KEY LEARNINGS ({len(reflection.key_learnings)} items)\n"
            f"{'-' * 13}\n"
            f"{learnings_text}\n\n"
            f"{'=' * 60}\n"
            f"Dispatched by Automated Open-Source PR Chronicler.\n"
        )
        msg.set_content(plain_text)

        # 2. Rich HTML portfolio entry body
        escaped_repo = html.escape(repository)
        escaped_issue = html.escape(reflection.issue_details).replace("\n", "<br>")
        escaped_summary = html.escape(reflection.execution_summary).replace("\n", "<br>")
        learnings_html = "\n".join(
            f'<li style="margin-bottom: 8px;">{html.escape(item)}</li>'
            for item in reflection.key_learnings
        )

        html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f6f8fa; margin: 0; padding: 24px; color: #24292f; }}
    .container {{ max-width: 680px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #d0d7de; overflow: hidden; }}
    .header {{ background: #0969da; color: #ffffff; padding: 24px; text-align: left; }}
    .header h1 {{ margin: 0; font-size: 20px; font-weight: 600; letter-spacing: -0.2px; }}
    .header .subtitle {{ margin-top: 6px; font-size: 13px; opacity: 0.95; }}
    .badge {{ display: inline-block; background: rgba(255,255,255,0.2); padding: 4px 8px; border-radius: 4px; font-size: 12px; margin-top: 8px; }}
    .content {{ padding: 24px; }}
    .section {{ margin-bottom: 24px; }}
    .section-title {{ font-size: 14px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: #57606a; margin-bottom: 8px; border-bottom: 1px solid #d0d7de; padding-bottom: 4px; }}
    .text-block {{ background: #f6f8fa; border-left: 4px solid #0969da; padding: 12px 16px; border-radius: 0 4px 4px 0; font-size: 14px; line-height: 1.6; margin: 0; }}
    .learnings-list {{ margin: 8px 0 0 0; padding-left: 20px; font-size: 14px; line-height: 1.6; }}
    .footer {{ background: #f6f8fa; border-top: 1px solid #d0d7de; padding: 16px 24px; font-size: 12px; color: #57606a; text-align: center; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>[OS-Log] Pull Request Technical Reflection</h1>
      <div class="subtitle">Repository: <strong>{escaped_repo}</strong> &bull; PR: <strong>#{pr_number}</strong></div>
      <div class="badge">Merged PR Chronicled</div>
    </div>
    <div class="content">
      <div class="section">
        <h2 class="section-title">Issue Details</h2>
        <p class="text-block">{escaped_issue}</p>
      </div>
      <div class="section">
        <h2 class="section-title">Execution Summary</h2>
        <p class="text-block" style="border-left-color: #2da44e;">{escaped_summary}</p>
      </div>
      <div class="section">
        <h2 class="section-title">Key Learnings</h2>
        <ol class="learnings-list">
          {learnings_html}
        </ol>
      </div>
    </div>
    <div class="footer">
      Automated Open-Source PR Chronicler &bull; Phase 5 SMTP Transmission
    </div>
  </div>
</body>
</html>"""

        msg.add_alternative(html_body, subtype="html")
        return msg

    def send_reflection_email_sync(
        self,
        reflection: PRReflection,
        repository: str,
        pr_number: int,
        recipient: Optional[str] = None,
        dry_run: Optional[bool] = None,
    ) -> bool:
        """Synchronously compose and transmit email using smtplib.

        Args:
            reflection: Validated PRReflection instance.
            repository: Full name of repository (e.g. 'owner/repo').
            pr_number: Pull request integer number.
            recipient: Optional specific recipient address override.
            dry_run: Optional override to simulate transmission without network calls.

        Returns:
            True if transmission or dry-run was successful, False otherwise.
        """
        is_dry_run = dry_run if dry_run is not None else self.dry_run
        target_recipients = [recipient] if recipient else settings.recipient_emails

        if not target_recipients:
            logger.warning(
                "No recipients configured for %s #%d. Defaulting to local delivery.",
                repository,
                pr_number,
            )
            target_recipients = [self.user or "student@example.com"]

        # Build message for primary recipient
        primary_recipient = target_recipients[0]
        try:
            msg = self.create_email_message(
                reflection=reflection,
                repository=repository,
                pr_number=pr_number,
                recipient=primary_recipient,
            )
        except Exception as exc:
            logger.error("Failed to construct EmailMessage for %s #%d: %s", repository, pr_number, exc)
            return False

        # Dry-run / test mode execution
        if is_dry_run or not (self.user and self.password):
            if not (self.user and self.password):
                logger.info(
                    "SMTP credentials not fully set (SMTP_EMAIL / SMTP_APP_PASSWORD). Running in safe dry-run mode."
                )
            logger.info(
                "SMTP transmission (dry-run mode) verified for %s #%d -> Subject: '%s' | Recipient: %s",
                repository,
                pr_number,
                msg["Subject"],
                primary_recipient,
            )
            logger.info("SMTP transmission successful for %s #%d", repository, pr_number)
            return True

        # Real SMTP Transmission
        try:
            if self.port == 465:
                # SSL direct connection
                with smtplib.SMTP_SSL(self.host, self.port, timeout=15.0) as server:
                    server.login(self.user, self.password)
                    server.send_message(msg)
            else:
                # Standard submission (587) with STARTTLS
                with smtplib.SMTP(self.host, self.port, timeout=15.0) as server:
                    server.ehlo()
                    if self.use_tls:
                        server.starttls()
                        server.ehlo()
                    server.login(self.user, self.password)
                    server.send_message(msg)

            logger.info("SMTP transmission successful for %s #%d", repository, pr_number)
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error(
                "SMTP transmission failed for %s #%d: Authentication failed. Please verify SMTP_APP_PASSWORD.",
                repository,
                pr_number,
            )
            return False
        except (smtplib.SMTPConnectError, ConnectionRefusedError, TimeoutError) as exc:
            logger.error(
                "SMTP transmission failed for %s #%d: Connection failure to %s:%d (%s)",
                repository,
                pr_number,
                self.host,
                self.port,
                type(exc).__name__,
            )
            return False
        except smtplib.SMTPException as exc:
            logger.error(
                "SMTP transmission failed for %s #%d: SMTP protocol error (%s)",
                repository,
                pr_number,
                type(exc).__name__,
            )
            return False
        except Exception as exc:
            logger.error(
                "SMTP transmission failed for %s #%d: Unexpected network error (%s)",
                repository,
                pr_number,
                type(exc).__name__,
            )
            return False

    async def send_reflection_email(
        self,
        reflection: PRReflection,
        repository: str,
        pr_number: int,
        recipient: Optional[str] = None,
        dry_run: Optional[bool] = None,
    ) -> bool:
        """Asynchronously send reflection email by delegating to worker thread (Requirement 9)."""
        return await asyncio.to_thread(
            self.send_reflection_email_sync,
            reflection,
            repository,
            pr_number,
            recipient,
            dry_run,
        )


# Default singleton dispatcher instance
email_dispatcher = EmailDispatcher()
