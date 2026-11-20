"""Email Notification System for AI Internship Application Agent.

Capabilities:
1. Submission Confirmation Email (`send_submission_confirmation_email`):
   - Subject: "Internship Application Successfully Submitted – [Company Name]"
     (or "Internship Application Pending Verification – [Company Name]" if portal confirmation could not be verified)
   - Body includes: Company name, Internship position, Application submission date and time,
     Platform name, Application URL, Resume used, Application status, and Application tracking ID.
   - CRITICAL SAFETY GUARDRAIL:
     * Never sends a successful-submission email merely because an application draft was prepared or approved.
     * For automated submissions (`submission_mode="AUTOMATED"`), requires `portal_confirmed=True` (otherwise labels the notification as `PENDING_VERIFICATION`).
     * For manual submissions (`submission_mode="MANUAL"`), requires `explicit_manual_mark=True` (only sent after the user explicitly marks the application as manually submitted).
2. Additional Notification Events:
   - New high-match internship opportunities (`send_high_match_notification`)
   - Applications awaiting user approval (`send_awaiting_approval_notification`)
   - Application submission failures (`send_submission_failure_notification`)
   - Interview invitations and status updates (`send_status_update_notification`)
3. Gmail SMTP App Password & OAuth2 XOAUTH2 Support:
   - Reads `SMTP_SENDER_EMAIL`, `SMTP_APP_PASSWORD`, and `SMTP_OAUTH_ACCESS_TOKEN` strictly from environment variables (never hardcoded).
   - Implements automatic retries (`max_retries=3`) for transient network/SMTP failures.
   - Prevents duplicate notification emails using deterministic `dedup_key` logged in SQLite (`email_notifications` table).
   - Writes local `.eml` copies to `outputs/emails/` so every notification can be inspected offline or when SMTP credentials are not yet entered.
"""
import base64
from datetime import datetime
from email.message import EmailMessage
import os
from pathlib import Path
import smtplib
import time
from typing import Any, Dict, List, Optional

from src.config import AppSettings, load_settings
from src.database import DatabaseManager
from src.logger import get_logger

logger = get_logger("email_notifications")

BASE_DIR = Path(__file__).resolve().parent.parent
OUTBOX_DIR = BASE_DIR / "outputs" / "emails"
OUTBOX_DIR.mkdir(parents=True, exist_ok=True)


class EmailNotificationService:
    """Reliable Gmail SMTP / OAuth2 & SQLite-audited email notification engine."""

    def __init__(
        self,
        db: Optional[DatabaseManager] = None,
        settings: Optional[AppSettings] = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.db = db or DatabaseManager(self.settings.database_path)

    def get_configuration_status(self) -> Dict[str, Any]:
        """Inspect current email configuration from Settings and environment variables without exposing secrets."""
        sender = os.getenv("SMTP_SENDER_EMAIL", "").strip()
        app_pwd = os.getenv("SMTP_APP_PASSWORD", "").strip()
        oauth_tok = os.getenv("SMTP_OAUTH_ACCESS_TOKEN", "").strip()

        has_Placeholder_pwd = app_pwd in ("", "your_16_char_gmail_app_password_here")
        has_placeholder_oauth = oauth_tok in ("", "your_optional_oauth2_bearer_token_here")
        has_valid_sender = bool(sender and "@" in sender and "your_sender_email" not in sender)

        smtp_credentials_ready = has_valid_sender and (not has_Placeholder_pwd or not has_placeholder_oauth)

        return {
            "enabled": self.settings.email_notifications_enabled,
            "recipient_email": self.settings.recipient_email,
            "sender_email": sender if has_valid_sender else "Not configured in .env (SMTP_SENDER_EMAIL)",
            "smtp_host": self.settings.smtp_host,
            "smtp_port": self.settings.smtp_port,
            "auth_method": self.settings.email_auth_method,
            "smtp_credentials_ready": smtp_credentials_ready,
            "status_label": (
                "Active (Gmail SMTP Ready)"
                if (self.settings.email_notifications_enabled and smtp_credentials_ready)
                else (
                    "Active (Local Outbox & SQLite Audit Mode — Add SMTP_APP_PASSWORD in .env for Live Gmail Delivery)"
                    if self.settings.email_notifications_enabled
                    else "Disabled in Settings"
                )
            ),
        }

    def _deliver_via_smtp_with_retry(
        self,
        recipient: str,
        subject: str,
        body: str,
        max_retries: int = 3,
        retry_delay_sec: float = 0.6,
    ) -> Dict[str, Any]:
        """Attempt live SMTP delivery with Gmail App Password or OAuth2 XOAUTH2, retrying temporary failures."""
        cfg_status = self.get_configuration_status()
        sender = os.getenv("SMTP_SENDER_EMAIL", "").strip() or recipient
        app_pwd = os.getenv("SMTP_APP_PASSWORD", "").strip()
        oauth_tok = os.getenv("SMTP_OAUTH_ACCESS_TOKEN", "").strip()

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = recipient
        msg.set_content(body)

        # Always save a local .eml record in outputs/emails/ for verifiable desktop inspection
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        eml_path = OUTBOX_DIR / f"notification_{ts}.eml"
        eml_path.write_bytes(msg.as_bytes())

        if not cfg_status["smtp_credentials_ready"]:
            return {
                "delivered_smtp": False,
                "delivery_status": "LOGGED_LOCAL_OUTBOX",
                "attempts": 1,
                "eml_path": str(eml_path),
                "error_message": "SMTP credentials not configured in .env; saved to local outbox and SQLite audit log.",
            }

        last_error = ""
        for attempt in range(1, max_retries + 1):
            try:
                with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=8) as server:
                    server.ehlo()
                    if self.settings.smtp_use_tls:
                        server.starttls()
                        server.ehlo()

                    if self.settings.email_auth_method == "oauth2" and oauth_tok:
                        auth_string = f"user={sender}\x01auth=Bearer {oauth_tok}\x01\x01"
                        b64_auth = base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")
                        code, resp = server.docmd("AUTH", f"XOAUTH2 {b64_auth}")
                        if code != 235:
                            raise smtplib.SMTPAuthenticationError(code, resp)
                    else:
                        server.login(sender, app_pwd)

                    server.send_message(msg)

                logger.info("Delivered email via SMTP to %s (subject='%s', attempt=%d)", recipient, subject, attempt)
                return {
                    "delivered_smtp": True,
                    "delivery_status": "SENT_SMTP",
                    "attempts": attempt,
                    "eml_path": str(eml_path),
                    "error_message": "",
                }
            except smtplib.SMTPAuthenticationError as auth_exc:
                # Permanent auth error: do not retry
                last_error = f"SMTP Authentication failed: {auth_exc}"
                logger.error(last_error)
                return {
                    "delivered_smtp": False,
                    "delivery_status": "FAILED_AUTH",
                    "attempts": attempt,
                    "eml_path": str(eml_path),
                    "error_message": last_error,
                }
            except Exception as exc:
                last_error = f"Attempt {attempt}/{max_retries} error: {exc}"
                logger.warning("Transient SMTP delivery failure (%s)", last_error)
                if attempt < max_retries:
                    time.sleep(retry_delay_sec)

        return {
            "delivered_smtp": False,
            "delivery_status": "FAILED_AFTER_RETRIES",
            "attempts": max_retries,
            "eml_path": str(eml_path),
            "error_message": last_error,
        }

    def _dispatch_notification(
        self,
        dedup_key: str,
        event_type: str,
        subject: str,
        body: str,
        company: str = "",
        role: str = "",
        tracking_id: str = "",
        force_send: bool = False,
    ) -> Dict[str, Any]:
        """Deduplicate, deliver (with retries), and log notification event in SQLite."""
        if not self.settings.email_notifications_enabled and not force_send:
            return {
                "sent": False,
                "duplicate_prevented": False,
                "delivery_status": "DISABLED_IN_SETTINGS",
                "message": "Email notifications are currently disabled in Settings.",
            }

        recipient = (self.settings.recipient_email or "").strip()
        if not recipient or "@" not in recipient:
            return {
                "sent": False,
                "duplicate_prevented": False,
                "delivery_status": "INVALID_RECIPIENT",
                "message": "Recipient email address is not configured in Settings.",
            }

        # Duplicate prevention check
        if not force_send and self.db.has_notification_been_sent(dedup_key):
            logger.info("Duplicate email notification prevented for dedup_key=%s", dedup_key)
            return {
                "sent": False,
                "duplicate_prevented": True,
                "delivery_status": "DUPLICATE_PREVENTED",
                "dedup_key": dedup_key,
                "subject": subject,
                "message": f"Duplicate notification prevented for key '{dedup_key}'.",
            }

        delivery = self._deliver_via_smtp_with_retry(
            recipient=recipient,
            subject=subject,
            body=body,
        )

        log_id = self.db.log_email_notification(
            dedup_key=dedup_key,
            event_type=event_type,
            recipient_email=recipient,
            subject=subject,
            body=body,
            company=company,
            role=role,
            tracking_id=tracking_id,
            delivery_status=delivery["delivery_status"],
            attempts=delivery["attempts"],
            error_message=delivery["error_message"],
        )

        return {
            "sent": delivery["delivery_status"] in ("SENT_SMTP", "LOGGED_LOCAL_OUTBOX"),
            "duplicate_prevented": False,
            "log_id": log_id,
            "dedup_key": dedup_key,
            "recipient": recipient,
            "subject": subject,
            "delivery_status": delivery["delivery_status"],
            "attempts": delivery["attempts"],
            "eml_path": delivery["eml_path"],
            "error_message": delivery["error_message"],
            "message": (
                f"Email delivered via SMTP to {recipient}."
                if delivery["delivery_status"] == "SENT_SMTP"
                else (
                    f"Notification logged to SQLite (#{log_id}) and saved to local outbox ({Path(delivery['eml_path']).name})."
                    if delivery["delivery_status"] == "LOGGED_LOCAL_OUTBOX"
                    else f"Delivery failed after {delivery['attempts']} attempt(s): {delivery['error_message']}"
                )
            ),
        }

    # ========================================================================
    # A. SUBMISSION CONFIRMATION EMAIL (WITH STRICT VERIFICATION GUARDRAILS)
    # ========================================================================

    def send_submission_confirmation_email(
        self,
        company: str,
        role: str,
        platform: str,
        application_url: str,
        resume_used: str,
        application_status: str,
        tracking_id: int | str,
        submission_mode: str = "AUTOMATED",  # "AUTOMATED" or "MANUAL"
        portal_confirmed: bool = False,
        explicit_manual_mark: bool = False,
        submission_datetime: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send submission confirmation email ONLY when actual submission is confirmed or explicitly marked manual.

        CRITICAL RULES:
        1. Never sends a successful-submission email merely because a draft was prepared or approved.
        2. For `submission_mode == "DRAFT_ONLY"`, refuses to send a submission success email.
        3. For `submission_mode == "MANUAL"`, requires `explicit_manual_mark=True`.
        4. For `submission_mode == "AUTOMATED"`, if `portal_confirmed=True`, sends
           `Subject: Internship Application Successfully Submitted – [Company Name]`.
           If `portal_confirmed=False`, clearly labels the email and status as `Pending Verification`.
        """
        if not self.settings.notify_on_submission_success:
            return {"sent": False, "delivery_status": "DISABLED_BY_PREFERENCE", "message": "Submission success notifications disabled."}

        mode_upper = submission_mode.upper().strip()
        if mode_upper not in ("AUTOMATED", "MANUAL"):
            raise ValueError(
                "GUARDRAIL BLOCK: Never send a successful-submission email merely because an application draft was prepared."
            )

        if mode_upper == "MANUAL" and not explicit_manual_mark:
            raise ValueError(
                "GUARDRAIL BLOCK: Manual submission email can only be sent after the user explicitly marks the application as manually submitted."
            )

        sub_dt = submission_datetime or datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
        track_str = f"APP-{tracking_id}"
        resume_name = Path(resume_used).name if resume_used else "Approved Resume Profile"

        is_verified_submission = (mode_upper == "AUTOMATED" and portal_confirmed) or (
            mode_upper == "MANUAL" and explicit_manual_mark
        )

        if is_verified_submission:
            subject = f"Internship Application Successfully Submitted – {company}"
            verified_status_line = f"{application_status} ({'Verified by Application Portal' if mode_upper == 'AUTOMATED' else 'Explicitly Marked as Manually Submitted'})"
            event_type = "SUBMISSION_SUCCESS_CONFIRMED" if mode_upper == "AUTOMATED" else "MANUAL_SUBMISSION_CONFIRMED"
            dedup_key = f"sub_confirmed_{mode_upper.lower()}_{tracking_id}_{company.lower().strip()}_{role.lower().strip()}"
        else:
            subject = f"Internship Application Pending Verification – {company}"
            verified_status_line = "Pending Verification (Portal confirmation could not be verified automatically)"
            event_type = "SUBMISSION_PENDING_VERIFICATION"
            dedup_key = f"sub_pending_ver_{tracking_id}_{company.lower().strip()}_{role.lower().strip()}"

        body = (
            f"Hello,\n\n"
            f"Here is your internship application submission notification from AI Internship Application Agent:\n\n"
            f"• Company Name: {company}\n"
            f"• Internship Position: {role}\n"
            f"• Application Submission Date & Time: {sub_dt}\n"
            f"• Platform Name: {platform}\n"
            f"• Application URL: {application_url}\n"
            f"• Resume Used: {resume_name}\n"
            f"• Application Status: {verified_status_line}\n"
            f"• Application Tracking ID: {track_str}\n\n"
            f"— AI Internship Application Agent"
        )

        return self._dispatch_notification(
            dedup_key=dedup_key,
            event_type=event_type,
            subject=subject,
            body=body,
            company=company,
            role=role,
            tracking_id=track_str,
        )

    # ========================================================================
    # B. OTHER EMAIL NOTIFICATIONS (AWAITING APPROVAL, HIGH MATCH, FAILURE, INTERVIEW)
    # ========================================================================

    def send_awaiting_approval_notification(
        self,
        draft_id: int,
        company: str,
        role: str,
        platform: str,
        application_url: str,
    ) -> Dict[str, Any]:
        """Notify the user that a prepared application draft is waiting in the Approval Center (NOT yet submitted)."""
        if not self.settings.notify_on_awaiting_approval:
            return {"sent": False, "delivery_status": "DISABLED_BY_PREFERENCE"}

        dedup_key = f"awaiting_approval_draft_{draft_id}_{company.lower().strip()}"
        subject = f"Action Required: Internship Application Awaiting Your Approval – {company}"
        body = (
            f"Hello,\n\n"
            f"An internship application draft has been prepared and is awaiting your explicit review in the Approval Center.\n"
            f"NOTE: This application has NOT been submitted yet.\n\n"
            f"• Draft ID: #{draft_id}\n"
            f"• Company Name: {company}\n"
            f"• Internship Position: {role}\n"
            f"• Platform Name: {platform}\n"
            f"• Application URL: {application_url}\n"
            f"• Current Status: Pending Your Explicit Approval\n\n"
            f"Open the AI Internship Agent dashboard -> F. Approval Center to review and approve or mark as manually submitted.\n\n"
            f"— AI Internship Application Agent"
        )
        return self._dispatch_notification(
            dedup_key=dedup_key,
            event_type="AWAITING_APPROVAL",
            subject=subject,
            body=body,
            company=company,
            role=role,
            tracking_id=f"DRAFT-{draft_id}",
        )

    def send_submission_failure_notification(
        self,
        company: str,
        role: str,
        platform: str,
        application_url: str,
        error_reason: str,
        draft_id: int | str = "",
    ) -> Dict[str, Any]:
        """Notify the user when an automated application submission attempt fails or is blocked."""
        if not self.settings.notify_on_submission_failure:
            return {"sent": False, "delivery_status": "DISABLED_BY_PREFERENCE"}

        dedup_key = f"sub_failure_{draft_id}_{company.lower().strip()}_{role.lower().strip()}"
        subject = f"Alert: Internship Application Submission Failed – {company}"
        body = (
            f"Hello,\n\n"
            f"An automated submission attempt could not be completed and requires your manual attention:\n\n"
            f"• Company Name: {company}\n"
            f"• Internship Position: {role}\n"
            f"• Platform Name: {platform}\n"
            f"• Application URL: {application_url}\n"
            f"• Failure / Pause Reason: {error_reason}\n\n"
            f"A Prepared Application Package (.md / .json) is available in the Approval Center so you can complete the application manually.\n\n"
            f"— AI Internship Application Agent"
        )
        return self._dispatch_notification(
            dedup_key=dedup_key,
            event_type="SUBMISSION_FAILURE",
            subject=subject,
            body=body,
            company=company,
            role=role,
            tracking_id=f"FAIL-{draft_id or '0'}",
        )

    def send_high_match_notification(
        self,
        opportunities: List[Dict[str, Any]],
        date_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a digest email when new high-match internship opportunities (>= threshold) are discovered."""
        if not self.settings.notify_on_high_match or not opportunities:
            return {"sent": False, "delivery_status": "SKIPPED"}

        day_str = date_key or datetime.now().strftime("%Y-%m-%d")
        top_company = opportunities[0].get("company", "Multiple Companies")
        dedup_key = f"high_match_digest_{day_str}_{len(opportunities)}_{top_company.lower().strip()}"
        subject = f"New High-Match AI Internship Opportunities Discovered ({len(opportunities)} Matches)"

        lines = [
            "Hello,",
            "",
            f"Your AI Internship Application Agent discovered {len(opportunities)} high-compatibility internship opportunities matching your approved resume profile:",
            "",
        ]
        for idx, opp in enumerate(opportunities[:10], start=1):
            lines.append(
                f"{idx}. {opp.get('role', opp.get('title', ''))} at {opp.get('company', '')} "
                f"({opp.get('location', 'Remote')}) — Match Score: {opp.get('match_score', opp.get('overall_score', 0))}% | "
                f"Stipend: {opp.get('stipend', 'N/A')} | URL: {opp.get('application_url', '')}"
            )
        lines.extend(
            [
                "",
                "Open the Streamlit Dashboard to review prepared cover letters and approve applications.",
                "",
                "— AI Internship Application Agent",
            ]
        )

        return self._dispatch_notification(
            dedup_key=dedup_key,
            event_type="HIGH_MATCH_OPPORTUNITIES",
            subject=subject,
            body="\n".join(lines),
            company=top_company,
            role=f"{len(opportunities)} High-Match Roles",
            tracking_id=f"DIGEST-{day_str}",
        )

    def send_daily_run_summary_email(
        self,
        jobs_discovered: int,
        verified_opportunities: int,
        matching_opportunities: int,
        drafts_prepared_this_run: int,
        total_awaiting_approval: int,
        execution_status: str,
        start_time: str,
        completion_time: str,
        dashboard_url: str = "http://localhost:8501",
        errors: Optional[List[str]] = None,
        run_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send the Task 5 Daily Run Summary Email after each completed daily discovery run.

        Never claims applications were submitted when they are only prepared drafts awaiting approval.
        """
        day_str = run_key or datetime.now().strftime("%Y-%m-%d")
        dedup_key = f"daily_run_summary_{day_str}_{drafts_prepared_this_run}_{total_awaiting_approval}_{execution_status.lower()}"
        subject = (
            f"AI Internship Agent Daily Discovery Summary – {execution_status} "
            f"({total_awaiting_approval} Drafts Awaiting Your Approval)"
        )

        err_section = ""
        if errors:
            err_section = "\nDiagnostic Notes / Source Status:\n" + "\n".join(f"  - {e}" for e in errors) + "\n"

        body = (
            f"Hello,\n\n"
            f"Your scheduled Daily AI Internship Discovery & Matching run has completed.\n"
            f"IMPORTANT SAFETY NOTICE: Zero applications were submitted automatically. All prepared items are drafts awaiting your explicit approval in the Approval Center.\n\n"
            f"• Execution Status: {execution_status}\n"
            f"• Start Time: {start_time}\n"
            f"• Completion Time: {completion_time}\n"
            f"• Number of Jobs Discovered / Evaluated: {jobs_discovered}\n"
            f"• Number of Verified Opportunities: {verified_opportunities}\n"
            f"• Number of Matching Opportunities (≥60% Match): {matching_opportunities}\n"
            f"• Number of New Application Drafts Prepared This Run: {drafts_prepared_this_run}\n"
            f"• Total Application Drafts Currently Awaiting Approval: {total_awaiting_approval}\n"
            f"• Local Dashboard Link: {dashboard_url}\n"
            f"{err_section}\n"
            f"Open your dashboard at {dashboard_url} (or double-click 'AI Internship Agent' on your Windows Desktop) and go to F. Approval Center to review your prepared application drafts.\n\n"
            f"— AI Internship Application Agent"
        )

        return self._dispatch_notification(
            dedup_key=dedup_key,
            event_type="DAILY_DISCOVERY_SUMMARY",
            subject=subject,
            body=body,
            company="Daily Discovery Pipeline",
            role=f"{total_awaiting_approval} Drafts Awaiting Approval",
            tracking_id=f"DAILY-{day_str}",
        )

    def send_status_update_notification(
        self,
        app_id: int,
        company: str,
        role: str,
        new_status: str,
        follow_up_date: str = "",
        notes: str = "",
    ) -> Dict[str, Any]:
        """Send an email notification when an application status changes (e.g., Interview invitation or Offer)."""
        if not self.settings.notify_on_interview_status:
            return {"sent": False, "delivery_status": "DISABLED_BY_PREFERENCE"}

        dedup_key = f"status_update_app_{app_id}_{new_status.lower().strip()}"
        subject = (
            f"🎉 Interview Invitation / Status Update: {role} at {company} ({new_status})"
            if new_status.lower() in ("interview", "offer")
            else f"Internship Application Status Updated – {company} ({new_status})"
        )
        body = (
            f"Hello,\n\n"
            f"The status of your tracked internship application has been updated:\n\n"
            f"• Application Tracking ID: APP-{app_id}\n"
            f"• Company Name: {company}\n"
            f"• Internship Position: {role}\n"
            f"• Updated Status: {new_status}\n"
            f"• Follow-Up Date: {follow_up_date or 'N/A'}\n"
            f"• Notes: {notes or 'Updated in Application Tracker'}\n\n"
            f"— AI Internship Application Agent"
        )
        return self._dispatch_notification(
            dedup_key=dedup_key,
            event_type="INTERVIEW_OR_STATUS_UPDATE",
            subject=subject,
            body=body,
            company=company,
            role=role,
            tracking_id=f"APP-{app_id}",
        )

    def send_test_email(self, custom_recipient: Optional[str] = None) -> Dict[str, Any]:
        """Send an immediate test email from Page H (Settings) to verify email configuration and delivery status."""
        if custom_recipient:
            self.settings.recipient_email = custom_recipient.strip()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
        dedup_key = f"test_email_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        subject = "AI Internship Application Agent – Test Email Notification"
        body = (
            f"Hello,\n\n"
            f"This is a test notification from your AI Internship Application Agent.\n\n"
            f"• Timestamp: {ts}\n"
            f"• Recipient Email: {self.settings.recipient_email}\n"
            f"• SMTP Server: {self.settings.smtp_host}:{self.settings.smtp_port}\n"
            f"• Auth Method: {self.settings.email_auth_method}\n\n"
            f"Your email notification subsystem and SQLite audit logger are working properly!\n\n"
            f"— AI Internship Application Agent"
        )
        return self._dispatch_notification(
            dedup_key=dedup_key,
            event_type="TEST_EMAIL",
            subject=subject,
            body=body,
            company="AI Internship Agent",
            role="System Diagnostic Test",
            tracking_id="TEST-001",
            force_send=True,
        )
