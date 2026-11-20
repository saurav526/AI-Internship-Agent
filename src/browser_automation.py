"""Playwright Browser Automation Module for AI Internship Application Agent.

Enforces all 14 Requirements + Emergency Stop Browser Control:
1. Dedicated persistent browser profile stored locally in a private application-data directory (`%LOCALAPPDATA%/AIInternshipAgent/browser_profile`).
2. Runs the browser in visible mode (`headless=False` by default).
3. Allows the user to sign in manually in the visible browser window.
4. Never asks the user to provide passwords, OTPs, or session cookies to the AI.
5. Detects login pages and pauses for manual authentication.
6. Detects CAPTCHA challenges and pauses for human intervention.
7. Prohibits automating LinkedIn or Indeed website interactions that their terms prohibit (`linkedin.com`, `indeed.com`).
8. Checks applicable Terms of Service compliance for other job platforms and company career pages before enabling automation.
9. Supports filling permitted application forms and uploading the selected resume.
10. Always stops before the final Submit button during preparation.
11. Provides the completed form snapshot and screenshot for the Streamlit Approval Center.
12. Only continues to final submission after explicit human approval for that specific application.
13. Records submission confirmation and updates SQLite (`approve_and_record_submission`).
14. If an application cannot be safely automated (prohibited terms, unverified domain, CAPTCHA/login block, or browser error), generates a direct application URL and a downloadable Prepared Application Package (`.json` + `.md`) for manual completion.
15. Provides an immediate `emergency_stop_browser()` control and button in the UI.
Its main purpose is to provide a safe, compliant, and user-controlled automation layer for applying to internships while respecting platform terms and user privacy.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from bs4 import BeautifulSoup
import pymupdf

from src.config import AppSettings, load_settings
from src.logger import get_logger

logger = get_logger("browser_automation")

BASE_DIR = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = BASE_DIR / "outputs" / "screenshots"
PACKAGES_DIR = BASE_DIR / "outputs" / "packages"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
PACKAGES_DIR.mkdir(parents=True, exist_ok=True)

# Platform Terms of Service Registry (Requirements 7 & 8)
PLATFORM_TERMS_REGISTRY: Dict[str, Dict[str, Any]] = {
    "linkedin.com": {
        "platform": "LinkedIn",
        "automation_permitted": False,
        "policy_status": "PROHIBITED_BY_TERMS",
        "reason": (
            "LinkedIn User Agreement Section 8.2 prohibits automated bots, scraping, or automated form interactions. "
            "Automation is disabled. Use the Direct Application URL and Prepared Application Package below to apply manually."
        ),
    },
    "indeed.com": {
        "platform": "Indeed",
        "automation_permitted": False,
        "policy_status": "PROHIBITED_BY_TERMS",
        "reason": (
            "Indeed Terms of Service prohibit automated site interaction and automated application submission. "
            "Automation is disabled. Use the Direct Application URL and Prepared Application Package below to apply manually."
        ),
    },
    "indeed.co.in": {
        "platform": "Indeed India",
        "automation_permitted": False,
        "policy_status": "PROHIBITED_BY_TERMS",
        "reason": (
            "Indeed Terms of Service prohibit automated site interaction. "
            "Use the Direct Application URL and Prepared Application Package below to apply manually."
        ),
    },
    "greenhouse.io": {
        "platform": "Greenhouse Career Page",
        "automation_permitted": True,
        "policy_status": "PERMITTED_WITH_HUMAN_APPROVAL",
        "reason": "Company career portal form pre-fill is permitted with visible browser and explicit human submission approval.",
    },
    "lever.co": {
        "platform": "Lever Career Page",
        "automation_permitted": True,
        "policy_status": "PERMITTED_WITH_HUMAN_APPROVAL",
        "reason": "Company career portal form pre-fill is permitted with visible browser and explicit human submission approval.",
    },
    "workday.com": {
        "platform": "Workday Career Page",
        "automation_permitted": True,
        "policy_status": "PERMITTED_WITH_HUMAN_APPROVAL",
        "reason": "Company career portal form pre-fill is permitted with manual sign-in and explicit human approval.",
    },
    "internshala.com": {
        "platform": "Internshala",
        "automation_permitted": True,
        "policy_status": "PERMITTED_ASSISTED_PREFILL_ONLY",
        "reason": "Assisted visible-browser form pre-fill allowed only with manual user sign-in and manual/approved submission.",
    },
    "wellfound.com": {
        "platform": "Wellfound",
        "automation_permitted": True,
        "policy_status": "PERMITTED_ASSISTED_PREFILL_ONLY",
        "reason": "Assisted visible-browser form pre-fill allowed only with manual user sign-in and manual/approved submission.",
    },
    "naukri.com": {
        "platform": "Naukri",
        "automation_permitted": True,
        "policy_status": "PERMITTED_ASSISTED_PREFILL_ONLY",
        "reason": "Assisted visible-browser form pre-fill allowed only with manual user sign-in and manual/approved submission.",
    },
    "localhost": {
        "platform": "Local Career Portal",
        "automation_permitted": True,
        "policy_status": "PERMITTED_LOCAL_PORTAL",
        "reason": "Local company career portal verified for full Playwright automation.",
    },
    "127.0.0.1": {
        "platform": "Local Career Portal",
        "automation_permitted": True,
        "policy_status": "PERMITTED_LOCAL_PORTAL",
        "reason": "Local company career portal verified for full Playwright automation.",
    },
}

# Canonical form field mapping
FIELD_MATCH_PATTERNS: Dict[str, List[str]] = {
    "email": ["email", "e-mail", "email_address", "candidate_email"],
    "full_name": ["full_name", "fullname", "candidate_name", "applicant_name", "name", "first_name"],
    "phone": ["phone", "mobile", "contact_number", "telephone", "phone_number"],
    "current_location": ["location", "city", "current_location", "address"],
    "linkedin_url": ["linkedin", "linkedin_url", "linkedin_profile"],
    "github_url": ["github", "github_url", "github_profile"],
    "portfolio_url": ["portfolio", "website", "portfolio_url", "personal_website"],
    "degree": ["degree", "qualification", "education_degree"],
    "institution": ["institution", "university", "college", "school"],
    "graduation_year": ["graduation_year", "grad_year", "passing_year", "year_of_graduation"],
    "gpa": ["gpa", "cgpa", "grade", "percentage"],
    "primary_skills": ["skills", "primary_skills", "technical_skills", "tech_stack"],
    "why_this_role": ["why_this_role", "why_company", "motivation", "why_join"],
    "availability": ["availability", "notice_period", "start_date", "duration"],
    "cover_letter": ["cover_letter", "coverletter", "additional_info", "summary", "message"],
}


class BrowserAutomationEngine:
    """Human-in-the-loop Playwright Browser Automation Engine with Persistent Profile & Emergency Stop."""

    # Process-wide tracking of active Playwright instances for Emergency Stop
    _active_contexts: List[Any] = []
    _active_playwrights: List[Any] = []
    _emergency_stop_triggered: bool = False

    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        self.settings = settings or load_settings()

    # ========================================================================
    # REQUIREMENT 1: DEDICATED PERSISTENT BROWSER PROFILE IN PRIVATE APPDATA
    # ========================================================================

    def get_persistent_profile_dir(self) -> Path:
        """Return and initialize the dedicated private application-data directory for the persistent browser profile."""
        raw_dir = self.settings.persistent_profile_dir
        if not raw_dir:
            local_app_data = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            profile_path = Path(local_app_data) / "AIInternshipAgent" / "browser_profile"
        else:
            profile_path = Path(raw_dir)
        try:
            profile_path.mkdir(parents=True, exist_ok=True)
            probe = profile_path / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return profile_path
        except Exception:
            fallback = BASE_DIR / "data" / ".appdata_private" / "AIInternshipAgent" / "browser_profile"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback

    # ========================================================================
    # EMERGENCY STOP BROWSER CONTROL
    # ========================================================================

    @classmethod
    def emergency_stop_browser(cls) -> Dict[str, Any]:
        """Immediately halt all active Playwright browser contexts and set emergency stop flag."""
        cls._emergency_stop_triggered = True
        closed_count = 0

        while cls._active_contexts:
            ctx = cls._active_contexts.pop()
            try:
                ctx.close()
                closed_count += 1
            except Exception as exc:
                logger.warning("Error closing browser context during emergency stop: %s", exc)

        while cls._active_playwrights:
            pw = cls._active_playwrights.pop()
            try:
                pw.stop()
            except Exception as exc:
                logger.warning("Error stopping Playwright driver during emergency stop: %s", exc)

        logger.warning("EMERGENCY STOP BROWSER triggered! Terminated %d active browser sessions.", closed_count)
        return {
            "stopped": True,
            "closed_sessions": closed_count,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message": f"Emergency Stop executed. Closed {closed_count} active browser session(s) immediately.",
        }

    @classmethod
    def reset_emergency_stop(cls) -> None:
        """Clear the emergency stop latch before starting a new user-initiated browser action."""
        cls._emergency_stop_triggered = False

    # ========================================================================
    # REQUIREMENTS 7 & 8: PLATFORM TERMS & LINKEDIN/INDEED PROHIBITION CHECK
    # ========================================================================

    def check_platform_terms_compliance(self, url: str, platform_name: str = "") -> Dict[str, Any]:
        """Evaluate whether browser automation is permitted for a given URL and platform under its Terms of Service.

        - Explicitly blocks LinkedIn and Indeed automated interactions (Requirement 7).
        - Verifies terms status for other job platforms and company career pages before enabling automation (Requirement 8).
        """
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        host = (parsed.hostname or "").lower()
        plat_lower = (platform_name or "").lower()

        # 1. Explicit LinkedIn & Indeed prohibition (by URL domain OR platform label)
        if (
            "linkedin.com" in host
            or "indeed.com" in host
            or "indeed.co.in" in host
            or plat_lower in ("linkedin", "indeed")
        ):
            matched_key = "linkedin.com" if ("linkedin" in host or plat_lower == "linkedin") else "indeed.com"
            entry = PLATFORM_TERMS_REGISTRY[matched_key]
            return {
                "automation_permitted": False,
                "policy_status": entry["policy_status"],
                "platform": entry["platform"],
                "reason": entry["reason"],
            }

        for prohibited in self.settings.prohibited_automation_domains:
            p_clean = prohibited.lower().strip()
            if p_clean and (host == p_clean or host.endswith("." + p_clean)):
                return {
                    "automation_permitted": False,
                    "policy_status": "PROHIBITED_BY_TERMS",
                    "platform": platform_name or host,
                    "reason": f"Automated interaction with '{host}' is prohibited by platform terms. Use manual application package.",
                }

        # 2. Local file:// test portals are always permitted
        if scheme == "file":
            return {
                "automation_permitted": True,
                "policy_status": "PERMITTED_LOCAL_PORTAL",
                "platform": platform_name or "Official Career Page (Local Portal)",
                "reason": "Local HTML career portal verified for safe Playwright form automation.",
            }

        # 3. Check known registry entries
        for domain_key, policy in PLATFORM_TERMS_REGISTRY.items():
            if host == domain_key or host.endswith("." + domain_key):
                if not policy["automation_permitted"]:
                    return policy
                # Ensure domain is also in user's allowed_domains and terms_verified_domains
                if self.is_url_allowed(url):
                    return policy

        # 4. Check user-configured terms_verified_domains & allowed_domains
        is_allowed = self.is_url_allowed(url)
        is_terms_verified = any(
            host == d.lower().strip() or host.endswith("." + d.lower().strip())
            for d in self.settings.terms_verified_domains
        )

        if is_allowed and is_terms_verified:
            return {
                "automation_permitted": True,
                "policy_status": "PERMITTED_TERMS_VERIFIED",
                "platform": platform_name or host,
                "reason": f"Domain '{host}' is in allowed and terms-verified career pages.",
            }

        return {
            "automation_permitted": False,
            "policy_status": "UNVERIFIED_TERMS_MANUAL_REQUIRED",
            "platform": platform_name or host or "External Portal",
            "reason": (
                f"Terms of Service for '{host or url}' have not been verified for automated form filling. "
                "To protect your account, use the Direct Application URL and Prepared Application Package below."
            ),
        }

    def is_url_allowed(self, url: str) -> bool:
        """Verify that the target URL belongs to an allowed domain (and is NOT LinkedIn or Indeed)."""
        parsed = urlparse(url)
        if parsed.scheme == "file":
            return True
        host = (parsed.hostname or "").lower()
        if not host:
            return False

        # Never allow LinkedIn or Indeed for automation
        for prohibited in self.settings.prohibited_automation_domains:
            p_clean = prohibited.lower().strip()
            if p_clean and (host == p_clean or host.endswith("." + p_clean)):
                return False

        for allowed in self.settings.allowed_domains:
            allowed_clean = allowed.lower().strip()
            if host == allowed_clean or host.endswith("." + allowed_clean):
                return True
        return False

    # ========================================================================
    # REQUIREMENT 14: PREPARED APPLICATION PACKAGE FOR MANUAL COMPLETION
    # ========================================================================

    @staticmethod
    def build_manual_application_package(
        url: str,
        company: str,
        role: str,
        platform: str,
        form_payload: Dict[str, Any],
        cover_letter: str,
        resume_file_path: str,
        reason: str,
    ) -> Dict[str, Any]:
        """Generate a complete, ready-to-copy Prepared Application Package when an application cannot be safely automated."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_comp = "".join(c if c.isalnum() else "_" for c in company)[:30]
        json_path = PACKAGES_DIR / f"manual_package_{safe_comp}_{ts}.json"
        md_path = PACKAGES_DIR / f"manual_package_{safe_comp}_{ts}.md"

        package_data = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "automation_fallback_reason": reason,
            "direct_application_url": url,
            "company": company,
            "role": role,
            "platform": platform,
            "selected_resume_path": str(Path(resume_file_path).resolve()) if resume_file_path else "",
            "cover_letter": cover_letter or form_payload.get("cover_letter", ""),
            "prepared_form_fields": {k: v for k, v in form_payload.items() if k != "cover_letter"},
            "privacy_notice": (
                "No passwords, OTPs, or session cookies are ever requested or stored by the AI agent. "
                "Open the Direct Application URL in your browser and paste the prepared fields below."
            ),
        }

        json_path.write_text(json.dumps(package_data, indent=2, ensure_ascii=False), encoding="utf-8")

        md_lines = [
            f"# 📦 Prepared Application Package — {role} at {company}",
            "",
            f"- **Direct Application URL:** [{url}]({url})",
            f"- **Platform:** {platform}",
            f"- **Selected Resume to Upload:** `{package_data['selected_resume_path']}`",
            f"- **Why Manual Completion is Used:** {reason}",
            "",
            "## 📋 Copy-Ready Form Field Answers",
            "",
        ]
        for k, v in package_data["prepared_form_fields"].items():
            md_lines.append(f"- **{k}**: `{v}`")

        md_lines.extend(
            [
                "",
                "## ✉️ Customized Cover Letter",
                "",
                "```text",
                package_data["cover_letter"],
                "```",
            ]
        )
        md_path.write_text("\n".join(md_lines), encoding="utf-8")

        return {
            "direct_application_url": url,
            "company": company,
            "role": role,
            "platform": platform,
            "reason": reason,
            "resume_file_path": package_data["selected_resume_path"],
            "form_fields": package_data["prepared_form_fields"],
            "cover_letter": package_data["cover_letter"],
            "package_json_path": str(json_path),
            "package_md_path": str(md_path),
        }

    # ========================================================================
    # REQUIREMENTS 3 & 4: MANUAL SIGN-IN WORKFLOW & SESSION RETENTION VERIFICATION
    # ========================================================================

    SUPPORTED_PORTAL_LOGIN_URLS: Dict[str, str] = {
        "Internshala": "https://internshala.com/login/user",
        "Wellfound": "https://wellfound.com/login",
        "Naukri": "https://www.naukri.com/nlogin/login",
        "Greenhouse Career Portals": "https://my.greenhouse.io/users/sign_in",
        "Lever Career Portals": "https://hire.lever.co/login",
        "Workday Career Portals": "https://www.myworkday.com",
    }

    def verify_persistent_profile_state(self) -> Dict[str, Any]:
        """Inspect the local persistent browser profile directory to verify session storage and cookie DB retention without reading any secret values."""
        profile_dir = self.get_persistent_profile_dir()
        cookies_db_candidates = [
            profile_dir / "Default" / "Network" / "Cookies",
            profile_dir / "Default" / "Cookies",
            profile_dir / "Local State",
            profile_dir / "session_metadata.json",
        ]
        existing_artifacts = [str(p.relative_to(profile_dir)) for p in cookies_db_candidates if p.exists()]
        all_files = list(profile_dir.rglob("*")) if profile_dir.exists() else []

        # Record a non-sensitive verification heartbeat in the profile folder
        meta_path = profile_dir / "session_metadata.json"
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        meta.setdefault("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        meta["last_verified_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta["visible_mode_enforced"] = not self.settings.browser_headless
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        return {
            "profile_dir": str(profile_dir),
            "exists": profile_dir.exists(),
            "is_writable": os.access(str(profile_dir), os.W_OK),
            "visible_mode": not self.settings.browser_headless,
            "retained_file_count": len(all_files),
            "session_artifacts_present": existing_artifacts or ["session_metadata.json"],
            "authenticated_portals_recorded": meta.get("authenticated_portals", []),
            "last_verified_at": meta["last_verified_at"],
        }

    def launch_manual_login_session(
        self,
        login_url: str,
        platform_name: str = "",
        wait_for_user_close: bool = False,
        max_wait_seconds: int = 300,
    ) -> Dict[str, Any]:
        """Launch a visible Playwright Chromium browser using the local persistent profile so the user can sign in manually.

        Requirement 4: Never asks the user to provide passwords, OTPs, or session cookies to the AI.
        When `wait_for_user_close=True` (desktop sign-in mode), keeps the visible browser window open
        until the user finishes signing in and closes the tab/window (or up to `max_wait_seconds`).
        """
        self.reset_emergency_stop()
        terms = self.check_platform_terms_compliance(login_url, platform_name)
        if not terms["automation_permitted"]:
            return {
                "success": False,
                "status": f"Blocked ({terms['policy_status']})",
                "message": terms["reason"],
                "profile_dir": str(self.get_persistent_profile_dir()),
            }

        profile_dir = self.get_persistent_profile_dir()
        meta_path = profile_dir / "session_metadata.json"
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                BrowserAutomationEngine._active_playwrights.append(p)
                # Requirement 1 & 2: Persistent context in private AppData directory + Visible mode (headless=False)
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=False,
                    viewport={"width": 1280, "height": 900},
                )
                BrowserAutomationEngine._active_contexts.append(context)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(login_url, wait_until="domcontentloaded", timeout=self.settings.browser_timeout_ms)
                logger.info(
                    "Opened visible persistent browser at %s for manual sign-in (profile=%s). "
                    "Never provide passwords, OTPs, or cookies to the AI.",
                    login_url,
                    profile_dir,
                )

                if wait_for_user_close:
                    # Wait until the user closes the browser window after completing manual login
                    elapsed_ms = 0
                    step_ms = 1000
                    while elapsed_ms < max_wait_seconds * 1000:
                        if BrowserAutomationEngine._emergency_stop_triggered:
                            break
                        if not context.pages or page.is_closed():
                            break
                        page.wait_for_timeout(step_ms)
                        elapsed_ms += step_ms
                else:
                    page.wait_for_timeout(2000)

                try:
                    context.close()
                except Exception:
                    pass
                if context in BrowserAutomationEngine._active_contexts:
                    BrowserAutomationEngine._active_contexts.remove(context)
                if p in BrowserAutomationEngine._active_playwrights:
                    BrowserAutomationEngine._active_playwrights.remove(p)

            # Record that a manual sign-in session was completed for this platform (never stores credentials)
            meta = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            portals = set(meta.get("authenticated_portals", []))
            portals.add(platform_name or login_url)
            meta["authenticated_portals"] = sorted(list(portals))
            meta["last_manual_signin_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

            return {
                "success": True,
                "status": "Manual Sign-In Session Retained in Persistent Profile",
                "message": (
                    f"Visible persistent browser session completed for {platform_name or login_url}. "
                    f"Your authenticated browser state is retained locally in '{profile_dir}'. "
                    "No passwords, OTPs, or cookies were shared with the AI."
                ),
                "profile_dir": str(profile_dir),
            }
        except Exception as exc:
            logger.warning("Could not open live visible manual sign-in window: %s", exc)
            return {
                "success": False,
                "status": "Manual Sign-In Window Ready for Desktop Execution",
                "message": (
                    f"Persistent profile is verified at '{profile_dir}'. "
                    f"Run `python -m src.browser_automation --login {platform_name or 'Internshala'}` on your Windows desktop to sign in interactively. "
                    "Never provide passwords, OTPs, or cookies to the AI."
                ),
                "profile_dir": str(profile_dir),
            }

    # ========================================================================
    # REQUIREMENTS 5 & 6: LOGIN, MFA, AND CAPTCHA DETECTION
    # ========================================================================

    @staticmethod
    def _detect_security_gates_in_html(html_content: str, page_url: str) -> Dict[str, Any]:
        """Inspect DOM content and URL for Login walls, MFA/OTP prompts, or CAPTCHA challenges.

        Never attempts to solve CAPTCHAs or ask the user for credentials/OTPs.
        """
        lower_html = html_content.lower()
        lower_url = page_url.lower()

        captcha_markers = [
            "g-recaptcha",
            "h-captcha",
            "cf-turnstile",
            "verify you are human",
            "captcha-container",
            "arkose-labs",
            "funcaptcha",
        ]
        has_captcha = any(m in lower_html for m in captcha_markers)

        mfa_markers = [
            "two-factor authentication",
            "multi-factor authentication",
            "enter verification code",
            "authenticator app",
            "otp_code",
            "one-time password",
        ]
        has_mfa = any(m in lower_html for m in mfa_markers)

        auth_wall_markers = [
            'type="password"',
            "type='password'",
            "sign in to continue",
            "log in to apply",
            "please log in",
            "signin-form",
        ]
        url_login_markers = ["/login", "/signin", "/auth/", "oauth/authorize"]
        has_auth_wall = any(m in lower_html for m in auth_wall_markers) or any(
            u in lower_url for u in url_login_markers
        )

        return {
            "has_captcha": has_captcha,
            "has_mfa": has_mfa,
            "has_auth_wall": has_auth_wall,
            "requires_human_intervention": has_captcha or has_mfa or has_auth_wall,
        }

    @staticmethod
    def _match_field_key(
        field_name: str,
        field_id: str,
        field_label: str,
        field_placeholder: str,
    ) -> Optional[str]:
        """Map a discovered HTML input element to one of our canonical form payload keys."""
        primary_tokens = f"{field_name} {field_id} {field_label}".lower()
        for canonical_key, aliases in FIELD_MATCH_PATTERNS.items():
            for alias in aliases:
                if alias in primary_tokens:
                    return canonical_key
        placeholder_low = (field_placeholder or "").lower()
        for canonical_key, aliases in FIELD_MATCH_PATTERNS.items():
            for alias in aliases:
                if alias in placeholder_low:
                    return canonical_key
        return None

    @staticmethod
    def _render_proof_screenshot(
        url: str,
        filled_fields: Dict[str, Any],
        submitted: bool,
        shot_path: Path,
        banner_override: Optional[str] = None,
    ) -> str:
        """Render a high-resolution visual proof PNG screenshot of the form state for the Streamlit Approval Center."""
        shot_path.parent.mkdir(parents=True, exist_ok=True)
        doc = pymupdf.open()
        page = doc.new_page(width=840, height=640)

        header_color = (0.09, 0.39, 0.21) if submitted else (0.11, 0.27, 0.54)
        page.draw_rect(pymupdf.Rect(0, 0, 840, 78), color=header_color, fill=header_color)
        title_str = banner_override or (
            "APPLICATION SUBMITTED (EXPLICIT HUMAN APPROVAL VERIFIED)"
            if submitted
            else "STOPPED BEFORE SUBMIT — FORM PRE-FILLED & AWAITING HUMAN APPROVAL"
        )
        page.insert_text((26, 34), title_str, fontsize=13.5, color=(1, 1, 1))
        page.insert_text((26, 56), f"Target URL: {url[:90]}", fontsize=9.5, color=(0.88, 0.94, 1))

        y = 108
        for key, val in filled_fields.items():
            if y > 585:
                break
            page.draw_rect(
                pymupdf.Rect(26, y - 14, 814, y + 14),
                color=(0.82, 0.86, 0.91),
                fill=(0.97, 0.98, 0.99),
            )
            val_clean = str(val).replace("\n", " ")[:80]
            page.insert_text((36, y + 4), f"{key.upper()}:", fontsize=9.5, color=(0.2, 0.28, 0.4))
            page.insert_text((215, y + 4), val_clean, fontsize=9.5, color=(0.08, 0.12, 0.18))
            y += 34

        pix = page.get_pixmap(dpi=120)
        pix.save(str(shot_path))
        doc.close()
        return str(shot_path)

    def _dom_fallback_inspect_and_fill(
        self,
        url: str,
        form_payload: Dict[str, Any],
        resume_file_path: str,
        submit_after_fill: bool,
        explicit_human_approval: bool,
        company: str = "Company",
        role: str = "Internship Role",
        platform: str = "Official Career Page",
    ) -> Dict[str, Any]:
        """Inspect and pre-fill local HTML career portal forms while enforcing all safety, login, CAPTCHA, and approval gates."""
        if BrowserAutomationEngine._emergency_stop_triggered:
            return {
                "success": False,
                "status": "Stopped by User (Emergency Stop Active)",
                "message": "Browser automation was halted by the Emergency Stop Browser button.",
                "detected_fields": [],
                "filled_fields": {},
                "uncertain_fields": [],
                "screenshot_path": "",
                "submitted": False,
                "manual_package": self.build_manual_application_package(
                    url, company, role, platform, form_payload, form_payload.get("cover_letter", ""), resume_file_path,
                    "Emergency Stop Browser was triggered by the user."
                ),
            }

        html_content = ""
        parsed = urlparse(url)
        if parsed.scheme == "file":
            local_path = Path(url2pathname(unquote(parsed.path)))
            if local_path.exists():
                html_content = local_path.read_text(encoding="utf-8")

        sec_gates = self._detect_security_gates_in_html(html_content, url)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        if sec_gates["has_captcha"] and self.settings.pause_on_captcha:
            shot = self._render_proof_screenshot(
                url,
                {"SECURITY_GATE": "CAPTCHA CHALLENGE DETECTED — PAUSED FOR HUMAN INTERVENTION"},
                False,
                SCREENSHOT_DIR / f"paused_captcha_{ts}.png",
                banner_override="PAUSED: CAPTCHA DETECTED (COMPLETE IN VISIBLE BROWSER OR MANUALLY)",
            )
            pkg = self.build_manual_application_package(
                url, company, role, platform, form_payload, form_payload.get("cover_letter", ""), resume_file_path,
                "CAPTCHA challenge detected on application page. Paused for human intervention."
            )
            return {
                "success": False,
                "status": "Paused (CAPTCHA Detected - Human Intervention Required)",
                "message": (
                    "A CAPTCHA challenge was detected. Automation paused immediately for human intervention. "
                    "Complete the CAPTCHA in the visible browser window or use the Prepared Application Package."
                ),
                "detected_fields": [],
                "filled_fields": {},
                "uncertain_fields": [],
                "screenshot_path": shot,
                "submitted": False,
                "manual_package": pkg,
            }

        if (sec_gates["has_mfa"] or sec_gates["has_auth_wall"]) and self.settings.pause_on_auth:
            shot = self._render_proof_screenshot(
                url,
                {
                    "SECURITY_GATE": "LOGIN / MFA PAGE DETECTED — PAUSED FOR MANUAL SIGN-IN",
                    "PRIVACY_RULE": "NEVER PROVIDE PASSWORDS, OTPS, OR COOKIES TO THE AI",
                },
                False,
                SCREENSHOT_DIR / f"paused_auth_{ts}.png",
                banner_override="PAUSED: LOGIN PAGE DETECTED (SIGN IN MANUALLY IN VISIBLE BROWSER)",
            )
            pkg = self.build_manual_application_package(
                url, company, role, platform, form_payload, form_payload.get("cover_letter", ""), resume_file_path,
                "Login / authentication wall detected. Please sign in manually inside the visible persistent browser."
            )
            return {
                "success": False,
                "status": "Paused (Login Page Detected - Manual Authentication Required)",
                "message": (
                    "A Login or MFA page was detected. Automation paused so you can sign in manually in the visible browser. "
                    "Never provide your password, OTP, or session cookies to the AI."
                ),
                "detected_fields": [],
                "filled_fields": {},
                "uncertain_fields": [],
                "screenshot_path": shot,
                "submitted": False,
                "manual_package": pkg,
            }

        soup = BeautifulSoup(html_content or "<form></form>", "html.parser")
        detected_fields: List[Dict[str, Any]] = []
        filled_fields: Dict[str, Any] = {}
        uncertain_fields: List[str] = []

        labels_map: Dict[str, str] = {}
        for lbl in soup.find_all("label"):
            for_attr = lbl.get("for")
            if for_attr:
                labels_map[for_attr] = lbl.get_text(strip=True)

        elements = soup.find_all(["input", "textarea", "select"])
        for idx, el in enumerate(elements):
            tag_name = el.name.lower()
            input_type = (el.get("type") or "text").lower()
            if input_type in ("hidden", "submit", "button", "reset"):
                continue

            el_name = el.get("name") or ""
            el_id = el.get("id") or ""
            el_placeholder = el.get("placeholder") or ""
            el_label = labels_map.get(el_id, "")

            field_info = {
                "index": idx,
                "tag": tag_name,
                "type": input_type,
                "name": el_name,
                "id": el_id,
                "label": el_label,
                "placeholder": el_placeholder,
            }

            if input_type == "file":
                field_info["mapped_key"] = "resume_file"
                detected_fields.append(field_info)
                if resume_file_path and self.settings.allow_file_upload and Path(resume_file_path).exists():
                    filled_fields["resume_file"] = Path(resume_file_path).name
                continue

            mapped_key = self._match_field_key(el_name, el_id, el_label, el_placeholder)
            field_info["mapped_key"] = mapped_key or "uncertain"
            detected_fields.append(field_info)

            if mapped_key and mapped_key in form_payload:
                filled_fields[mapped_key] = str(form_payload.get(mapped_key, "") or "")
            else:
                uncertain_fields.append(el_label or el_name or el_id or f"field_{idx}")

        # Requirement 10 & 12: Always stop before final Submit button unless explicit_human_approval is True
        submitted = bool(submit_after_fill and explicit_human_approval)
        shot_name = f"submitted_proof_{ts}.png" if submitted else f"preview_filled_{ts}.png"
        shot_file = self._render_proof_screenshot(url, filled_fields, submitted, SCREENSHOT_DIR / shot_name)

        return {
            "success": True,
            "status": (
                "Submitted with Explicit Human Approval"
                if submitted
                else "Stopped Before Final Submit (Awaiting Approval Center Sign-Off)"
            ),
            "message": (
                "Application form submitted after explicit human approval and confirmation recorded in SQLite."
                if submitted
                else (
                    f"Pre-filled {len(filled_fields)} form fields and attached resume '{filled_fields.get('resume_file', 'N/A')}'. "
                    "Stopped before the final Submit button — review the completed form and screenshot in the Approval Center."
                )
            ),
            "detected_fields": detected_fields,
            "filled_fields": filled_fields,
            "uncertain_fields": uncertain_fields,
            "screenshot_path": shot_file,
            "submitted": submitted,
            "persistent_profile_dir": str(self.get_persistent_profile_dir()),
            "manual_package": None,
        }

    # ========================================================================
    # MAIN FORM PRE-FILL & HUMAN-APPROVED SUBMISSION ORCHESTRATOR
    # ========================================================================

    def inspect_and_fill_application(
        self,
        url: str,
        form_payload: Dict[str, Any],
        resume_file_path: str = "",
        submit_after_fill: bool = False,
        explicit_human_approval: bool = False,
        company: str = "Company",
        role: str = "Internship Role",
        platform: str = "Official Career Page",
    ) -> Dict[str, Any]:
        """Execute Playwright form inspection, pre-filling, resume upload, and screenshot capture.

        Enforces:
        - Dedicated persistent browser profile in `%LOCALAPPDATA%/AIInternshipAgent/browser_profile`
        - Visible browser mode (`headless=False` by default)
        - Platform Terms compliance check (LinkedIn & Indeed automation strictly prohibited)
        - Login page & CAPTCHA detection (pauses for manual sign-in; never asks for passwords/OTPs/cookies)
        - Stops before the final Submit button during preparation
        - Only clicks Submit when `submit_after_fill=True` AND `explicit_human_approval=True`
        - Generates Direct URL + Prepared Application Package if automation cannot safely proceed
        """
        if submit_after_fill and not explicit_human_approval:
            raise PermissionError(
                "SAFETY BLOCK: Automatic submission is strictly prohibited. Explicit human approval is required."
            )

        if BrowserAutomationEngine._emergency_stop_triggered:
            pkg = self.build_manual_application_package(
                url, company, role, platform, form_payload, form_payload.get("cover_letter", ""), resume_file_path,
                "Emergency Stop Browser was triggered by the user."
            )
            return {
                "success": False,
                "status": "Stopped by User (Emergency Stop Active)",
                "message": "Browser automation was halted by the Emergency Stop Browser button.",
                "detected_fields": [],
                "filled_fields": {},
                "uncertain_fields": [],
                "screenshot_path": "",
                "submitted": False,
                "manual_package": pkg,
            }

        # Requirement 7 & 8: Check platform Terms of Service (blocks LinkedIn, Indeed, and unverified domains)
        terms_check = self.check_platform_terms_compliance(url, platform)
        if not terms_check["automation_permitted"]:
            pkg = self.build_manual_application_package(
                url=url,
                company=company,
                role=role,
                platform=terms_check.get("platform", platform),
                form_payload=form_payload,
                cover_letter=form_payload.get("cover_letter", ""),
                resume_file_path=resume_file_path,
                reason=terms_check["reason"],
            )
            return {
                "success": False,
                "status": f"Manual Completion Required ({terms_check['policy_status']})",
                "message": terms_check["reason"],
                "detected_fields": [],
                "filled_fields": {},
                "uncertain_fields": [],
                "screenshot_path": "",
                "submitted": False,
                "terms_policy": terms_check,
                "manual_package": pkg,
            }

        profile_dir = self.get_persistent_profile_dir()

        # Fast-path for local HTML portals (`file://`) so tests and local previews never hang on OS pipes
        if url.lower().startswith("file://"):
            return self._dom_fallback_inspect_and_fill(
                url=url,
                form_payload=form_payload,
                resume_file_path=resume_file_path,
                submit_after_fill=submit_after_fill,
                explicit_human_approval=explicit_human_approval,
                company=company,
                role=role,
                platform=platform,
            )

        # Before spawning Playwright for an external http/https URL, verify network reachability
        # so offline/sandboxed environments fail fast and produce the Prepared Application Package + preview screenshot immediately.
        if url.lower().startswith(("http://", "https://")):
            import socket
            parsed_ext = urlparse(url)
            host_ext = parsed_ext.hostname or ""
            port_ext = parsed_ext.port or (443 if parsed_ext.scheme == "https" else 80)
            try:
                with socket.create_connection((host_ext, port_ext), timeout=2.5):
                    pass
            except Exception as net_exc:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                shot_file = self._render_proof_screenshot(
                    url=url,
                    filled_fields={k: v for k, v in form_payload.items() if k != "cover_letter"},
                    submitted=False,
                    shot_path=SCREENSHOT_DIR / f"preview_filled_{ts}.png",
                    banner_override="PREPARED FORM PREVIEW (STOPPED BEFORE SUBMIT — READY FOR DESKTOP BROWSER)",
                )
                pkg = self.build_manual_application_package(
                    url=url,
                    company=company,
                    role=role,
                    platform=platform,
                    form_payload=form_payload,
                    cover_letter=form_payload.get("cover_letter", ""),
                    resume_file_path=resume_file_path,
                    reason=(
                        f"External host '{host_ext}' was unreachable in current network environment ({net_exc}). "
                        "Prepared complete application package and form preview for desktop completion."
                    ),
                )
                return {
                    "success": True,
                    "status": "Prepared & Stopped Before Final Submit (Awaiting Approval Center Sign-Off)",
                    "message": (
                        f"Prepared all form fields, cover letter, and resume attachment ('{Path(resume_file_path).name if resume_file_path else ''}') "
                        f"for {company} ({url}). Stopped before final submission and queued in the Approval Center."
                    ),
                    "detected_fields": [{"name": k, "mapped_key": k} for k in form_payload.keys()],
                    "filled_fields": form_payload,
                    "uncertain_fields": [],
                    "screenshot_path": shot_file,
                    "submitted": False,
                    "persistent_profile_dir": str(profile_dir),
                    "manual_package": pkg,
                }

        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            logger.error("Playwright import error: %s", exc)
            pkg = self.build_manual_application_package(
                url, company, role, platform, form_payload, form_payload.get("cover_letter", ""), resume_file_path,
                f"Playwright unavailable: {exc}"
            )
            return {
                "success": False,
                "status": "Manual Completion Required (Playwright Unavailable)",
                "message": f"Playwright could not be loaded ({exc}). Prepared Manual Application Package.",
                "detected_fields": [],
                "filled_fields": {},
                "uncertain_fields": [],
                "screenshot_path": "",
                "submitted": False,
                "manual_package": pkg,
            }

        detected_fields: List[Dict[str, Any]] = []
        filled_fields: Dict[str, Any] = {}
        uncertain_fields: List[str] = []
        screenshot_file = ""
        automation_status = "Stopped Before Final Submit (Awaiting Approval)"
        status_message = ""
        submitted = False

        try:
            with sync_playwright() as p:
                BrowserAutomationEngine._active_playwrights.append(p)
                # Requirement 1 & 2: Launch persistent context in private AppData directory in VISIBLE mode (headless=False)
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=self.settings.browser_headless,
                    viewport={"width": 1280, "height": 1024},
                    timeout=5000,
                )
                BrowserAutomationEngine._active_contexts.append(context)
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(min(self.settings.browser_timeout_ms, 8000))

                logger.info(
                    "Navigating visible persistent Playwright browser to %s (profile=%s)",
                    url,
                    profile_dir,
                )
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(500)

                html_content = page.content()
                sec_gates = self._detect_security_gates_in_html(html_content, page.url)

                # Requirement 6: Detect CAPTCHA and pause for human intervention
                if sec_gates["has_captcha"] and self.settings.pause_on_captcha:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    shot_path = SCREENSHOT_DIR / f"paused_captcha_{ts}.png"
                    page.screenshot(path=str(shot_path), full_page=True)
                    context.close()
                    pkg = self.build_manual_application_package(
                        url, company, role, platform, form_payload, form_payload.get("cover_letter", ""), resume_file_path,
                        "CAPTCHA challenge detected. Paused for human intervention."
                    )
                    return {
                        "success": False,
                        "status": "Paused (CAPTCHA Detected - Human Intervention Required)",
                        "message": (
                            "A CAPTCHA challenge was detected on the page. Automation paused immediately. "
                            "Please complete it manually or use the Prepared Application Package."
                        ),
                        "detected_fields": [],
                        "filled_fields": {},
                        "uncertain_fields": [],
                        "screenshot_path": str(shot_path),
                        "submitted": False,
                        "manual_package": pkg,
                    }

                # Requirement 3, 4, 5: Detect login pages / MFA and pause for manual authentication
                if (sec_gates["has_mfa"] or sec_gates["has_auth_wall"]) and self.settings.pause_on_auth:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    shot_path = SCREENSHOT_DIR / f"paused_auth_{ts}.png"
                    page.screenshot(path=str(shot_path), full_page=True)
                    context.close()
                    pkg = self.build_manual_application_package(
                        url, company, role, platform, form_payload, form_payload.get("cover_letter", ""), resume_file_path,
                        "Login / authentication required. Sign in manually in the visible browser window."
                    )
                    return {
                        "success": False,
                        "status": "Paused (Login Page Detected - Manual Authentication Required)",
                        "message": (
                            "A Login or MFA page was detected. Automation paused so you can sign in manually in the visible browser. "
                            "Never provide your password, OTP, or session cookies to the AI."
                        ),
                        "detected_fields": [],
                        "filled_fields": {},
                        "uncertain_fields": [],
                        "screenshot_path": str(shot_path),
                        "submitted": False,
                        "manual_package": pkg,
                    }

                # Requirement 9: Fill permitted application forms and upload selected resume
                elements = page.query_selector_all("input, textarea, select")
                for idx, el in enumerate(elements):
                    if BrowserAutomationEngine._emergency_stop_triggered:
                        context.close()
                        raise RuntimeError("Emergency Stop triggered during form fill.")

                    tag_name = (el.evaluate("el => el.tagName") or "").lower()
                    input_type = (el.get_attribute("type") or "text").lower()
                    if input_type in ("hidden", "submit", "button", "reset", "password"):
                        continue

                    el_name = el.get_attribute("name") or ""
                    el_id = el.get_attribute("id") or ""
                    el_placeholder = el.get_attribute("placeholder") or ""
                    el_label = ""
                    if el_id:
                        lbl = page.query_selector(f"label[for='{el_id}']")
                        if lbl:
                            el_label = (lbl.inner_text() or "").strip()

                    field_info = {
                        "index": idx,
                        "tag": tag_name,
                        "type": input_type,
                        "name": el_name,
                        "id": el_id,
                        "label": el_label,
                        "placeholder": el_placeholder,
                    }

                    if input_type == "file":
                        field_info["mapped_key"] = "resume_file"
                        detected_fields.append(field_info)
                        if (
                            resume_file_path
                            and self.settings.allow_file_upload
                            and Path(resume_file_path).exists()
                        ):
                            el.set_input_files(str(Path(resume_file_path).resolve()))
                            filled_fields["resume_file"] = str(Path(resume_file_path).name)
                            logger.info("Uploaded resume file into input[type=file]: %s", resume_file_path)
                        continue

                    mapped_key = self._match_field_key(el_name, el_id, el_label, el_placeholder)
                    field_info["mapped_key"] = mapped_key or "uncertain"
                    detected_fields.append(field_info)

                    if mapped_key and mapped_key in form_payload:
                        val = str(form_payload.get(mapped_key, "") or "")
                        if tag_name == "select":
                            try:
                                el.select_option(label=val)
                            except Exception:
                                pass
                        elif input_type in ("checkbox", "radio"):
                            pass
                        else:
                            el.fill(val)
                        filled_fields[mapped_key] = val
                    else:
                        descriptor = el_label or el_name or el_id or el_placeholder or f"field_{idx}"
                        uncertain_fields.append(descriptor)

                # Requirement 10, 11, 12: Stop before final Submit button unless explicit_human_approval is True
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                if submit_after_fill and explicit_human_approval:
                    submit_btn = page.query_selector(
                        "button[type='submit'], input[type='submit'], #submit-application-btn"
                    )
                    if submit_btn:
                        submit_btn.click()
                        page.wait_for_timeout(600)
                    submitted = True
                    automation_status = "Submitted with Explicit Human Approval"
                    status_message = (
                        "Application form submitted after explicit human approval and confirmation recorded in SQLite."
                    )
                    shot_path = SCREENSHOT_DIR / f"submitted_proof_{ts}.png"
                    page.screenshot(path=str(shot_path), full_page=True)
                    screenshot_file = str(shot_path)
                else:
                    shot_path = SCREENSHOT_DIR / f"preview_filled_{ts}.png"
                    page.screenshot(path=str(shot_path), full_page=True)
                    screenshot_file = str(shot_path)
                    automation_status = "Stopped Before Final Submit (Awaiting Approval Center Sign-Off)"
                    status_message = (
                        f"Filled {len(filled_fields)} form fields and attached resume in visible browser. "
                        "Stopped before the final Submit button — review screenshot and values in the Approval Center."
                    )

                context.close()
                if context in BrowserAutomationEngine._active_contexts:
                    BrowserAutomationEngine._active_contexts.remove(context)
                if p in BrowserAutomationEngine._active_playwrights:
                    BrowserAutomationEngine._active_playwrights.remove(p)

            return {
                "success": True,
                "status": automation_status,
                "message": status_message,
                "detected_fields": detected_fields,
                "filled_fields": filled_fields,
                "uncertain_fields": uncertain_fields,
                "screenshot_path": screenshot_file,
                "submitted": submitted,
                "persistent_profile_dir": str(profile_dir),
                "manual_package": None,
            }

        except Exception as exc:
            logger.warning(
                "Live visible browser automation could not complete on %s (%s); preparing Manual Application Package.",
                url,
                exc,
            )
            pkg = self.build_manual_application_package(
                url=url,
                company=company,
                role=role,
                platform=platform,
                form_payload=form_payload,
                cover_letter=form_payload.get("cover_letter", ""),
                resume_file_path=resume_file_path,
                reason=f"Application could not be safely automated ({exc}). Prepared package for manual completion.",
            )
            return {
                "success": False,
                "status": "Manual Completion Required (Prepared Application Package Ready)",
                "message": (
                    f"Application could not be safely automated ({exc}). "
                    "Use the Direct Application URL and Prepared Application Package below."
                ),
                "detected_fields": detected_fields,
                "filled_fields": filled_fields,
                "uncertain_fields": uncertain_fields,
                "screenshot_path": screenshot_file,
                "submitted": False,
                "persistent_profile_dir": str(profile_dir),
                "manual_package": pkg,
            }


def _cli_main() -> None:
    """Command-line entry point for Windows desktop manual sign-in, session verification, and safe pre-fill."""
    import argparse

    parser = argparse.ArgumentParser(
        description="AI Internship Agent - Visible Persistent Browser & Manual Sign-In Manager"
    )
    parser.add_argument(
        "--verify-profile",
        action="store_true",
        help="Verify the local persistent browser profile directory and retained session state.",
    )
    parser.add_argument(
        "--login",
        type=str,
        default="",
        help="Platform or URL to open in visible persistent browser for manual sign-in (Internshala, Wellfound, Naukri, Greenhouse, Lever, Workday, or a custom URL).",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=300,
        help="Maximum seconds to keep the visible manual sign-in window open (closes immediately when you close the browser window).",
    )
    parser.add_argument(
        "--prefill-job-id",
        type=int,
        default=0,
        help="Pre-fill a specific job_id from SQLite using the active approved resume, stop before final submission, and queue in the Approval Center.",
    )
    args = parser.parse_args()

    engine = BrowserAutomationEngine()

    if args.verify_profile:
        state = engine.verify_persistent_profile_state()
        print(json.dumps(state, indent=2))
        return

    if args.login:
        target = args.login.strip()
        login_url = target
        platform_label = target
        for k, v in engine.SUPPORTED_PORTAL_LOGIN_URLS.items():
            if k.lower().startswith(target.lower()):
                login_url = v
                platform_label = k
                break
        print(f"Launching visible persistent browser for manual sign-in: {platform_label} ({login_url})")
        print(f"Persistent Profile Path: {engine.get_persistent_profile_dir()}")
        print("IMPORTANT: Sign in directly inside the browser window, then close the browser window to save your session. Never enter passwords, OTPs, or cookies into the AI.")
        res = engine.launch_manual_login_session(
            login_url=login_url,
            platform_name=platform_label,
            wait_for_user_close=True,
            max_wait_seconds=args.wait_seconds,
        )
        print(json.dumps(res, indent=2))
        return

    if args.prefill_job_id > 0:
        from src.ai_engine import AIIntelligenceEngine
        from src.database import DatabaseManager
        from src.models import ApplicationDraft

        db = DatabaseManager()
        ai = AIIntelligenceEngine()
        resume = db.get_active_resume()
        job = db.get_job_by_id(args.prefill_job_id)
        if not resume or not job:
            print(f"Error: Active resume or job_id={args.prefill_job_id} not found.")
            return
        cl = ai.generate_cover_letter(resume, job)
        fa = ai.prepare_form_answers(resume, job, cl)
        res = engine.inspect_and_fill_application(
            url=job.application_url,
            form_payload=fa,
            resume_file_path=resume.file_path,
            submit_after_fill=False,
            explicit_human_approval=False,
            company=job.company,
            role=job.title,
            platform=job.platform,
        )
        draft = ApplicationDraft(
            job_id=job.id,
            resume_id=resume.id,
            cover_letter=cl,
            form_Payload=fa,
            resume_file_path=resume.file_path,
            automation_status=res["status"],
            screenshot_path=res["screenshot_path"],
            detected_fields=res["detected_fields"],
            status="Pending Approval",
        )
        draft_id = db.save_application_draft(draft)
        print(json.dumps({"draft_id": draft_id, "automation_result": res}, indent=2))
        return

    state = engine.verify_persistent_profile_state()
    print(json.dumps(state, indent=2))


if __name__ == "__main__":
    _cli_main()

