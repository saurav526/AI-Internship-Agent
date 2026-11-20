"""Daily Internship Discovery & Ranking Automation Pipeline.

Executes the scheduled daily workflow (every day at 09:00 AM IST):
1. Prevents overlapping / duplicate concurrent executions via a process lock file (`data/daily_automation.lock`).
2. Discovers new AI Engineer, Agentic AI, Generative AI, Machine Learning, and Data Science
   internship opportunities in India, Pune, and Remote locations using permitted public job sources
   and official company career pages (never scraping or automating LinkedIn or Indeed).
3. Verifies available source information and original URLs (`is_verified_source`, `verification_status`).
4. Compares all discovered opportunities against the user's approved active resume profile.
5. Removes duplicates and filters out expired listings.
6. Generates a ranked list of the top 20 most relevant opportunities (including company, role,
   location, stipend, match score, source verification, and application URL).
7. Scans through ALL eligible ranked opportunities (skipping already-applied or already-pending jobs)
   until it prepares up to `prepare_top_n_drafts` customized cover letters and application form answers,
   saving them to SQLite so they immediately appear in the Approval Center.
8. Records start time, completion time, duration, and execution status in `outputs/daily_discovery_report.md`,
   `outputs/daily_discovery_report.json`, and `logs/daily_scheduler.log`.
9. Sends the Task 5 Daily Run Summary Email notification (never claiming drafts were submitted).
10. Never submits applications, sends messages, uploads personal information, or performs account
    actions without explicit human approval.
"""
import json
import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from src.ai_engine import AIIntelligenceEngine
from src.config import load_settings
from src.database import DatabaseManager
from src.job_discovery import JobDiscoveryEngine
from src.logger import get_logger
from src.models import ApplicationDraft, JobListing
from src.sample_data import ensure_sample_environment

logger = get_logger("daily_automation")

BASE_DIR = Path(__file__).resolve().parent.parent
REPORT_MD_PATH = BASE_DIR / "outputs" / "daily_discovery_report.md"
REPORT_JSON_PATH = BASE_DIR / "outputs" / "daily_discovery_report.json"
SCHEDULER_LOG_PATH = BASE_DIR / "logs" / "daily_scheduler.log"
LOCK_FILE_PATH = BASE_DIR / "data" / "daily_automation.lock"

TARGET_DAILY_ROLES = [
    "AI Engineer",
    "Agentic AI Developer",
    "Generative AI Engineer",
    "Machine Learning Engineer",
    "Data Scientist",
]

TARGET_DAILY_LOCATIONS = ["India", "Pune", "Remote", "Bangalore", "Hyderabad", "Delhi NCR", "Mumbai", "Chennai"]

PROHIBITED_SCRAPE_PLATFORMS = {"linkedin", "indeed"}


def _append_scheduler_log(line: str) -> None:
    """Append a timestamped diagnostic entry to logs/daily_scheduler.log."""
    try:
        SCHEDULER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
        with open(SCHEDULER_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {line}\n")
    except Exception as exc:
        logger.warning("Could not write to daily_scheduler.log: %s", exc)


def _acquire_execution_lock(max_stale_minutes: int = 30) -> bool:
    """Acquire an exclusive lock file to prevent overlapping or duplicate discovery processes."""
    LOCK_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE_PATH.exists():
        try:
            lock_data = json.loads(LOCK_FILE_PATH.read_text(encoding="utf-8"))
            started_str = lock_data.get("started_at", "")
            pid = lock_data.get("pid", 0)
            if started_str:
                age_sec = (datetime.now() - datetime.strptime(started_str, "%Y-%m-%d %H:%M:%S")).total_seconds()
                if age_sec < max_stale_minutes * 60 and pid != os.getpid():
                    return False
        except Exception:
            pass

    LOCK_FILE_PATH.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return True


def _release_execution_lock() -> None:
    """Release the execution lock file."""
    try:
        if LOCK_FILE_PATH.exists():
            LOCK_FILE_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def _is_expired(posted_date_str: str, max_age_days: int = 45) -> bool:
    """Return True if a job listing's posted_date is older than max_age_days."""
    if not posted_date_str:
        return False
    try:
        posted_dt = datetime.strptime(posted_date_str[:10], "%Y-%m-%d")
        age = (datetime.now() - posted_dt).days
        return age > max_age_days
    except Exception:
        return False


def run_daily_discovery_pipeline(top_k: int = 20, prepare_top_n_drafts: int = 5) -> Dict[str, Any]:
    """Run the complete daily discovery, matching, deduplication, draft preparation, email notification, and reporting pipeline."""
    start_dt = datetime.now()
    start_time_str = start_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    if not _acquire_execution_lock():
        msg = "Duplicate / overlapping execution prevented: Another daily_automation process is currently active."
        logger.warning(msg)
        _append_scheduler_log(f"SKIPPED_OVERLAP | {msg}")
        return {
            "success": False,
            "execution_status": "SKIPPED_OVERLAPPING_PROCESS",
            "start_time": start_time_str,
            "completion_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
            "errors": [msg],
        }

    _append_scheduler_log(f"START | Daily Internship Discovery Pipeline triggered (PID={os.getpid()}).")
    errors_and_unavailable_sources: List[str] = []
    execution_status = "SUCCESS"

    try:
        settings = load_settings()
        db = DatabaseManager(settings.database_path)
        ensure_sample_environment(db)

        ai_engine = AIIntelligenceEngine(settings)
        discovery_engine = JobDiscoveryEngine(daily_limit=settings.daily_discovery_limit)

        # 1. Verify active approved resume profile
        active_resume = db.get_active_resume()
        if not active_resume:
            msg = "No active approved resume profile found in SQLite database."
            logger.error(msg)
            errors_and_unavailable_sources.append(msg)
            _append_scheduler_log(f"FAILURE | {msg}")
            return {
                "success": False,
                "execution_status": "FAILED_NO_ACTIVE_RESUME",
                "start_time": start_time_str,
                "completion_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
                "errors": errors_and_unavailable_sources,
            }

        # 2. Discover from permitted public sources & official company career pages (never scraping LinkedIn or Indeed)
        raw_candidates: List[JobListing] = []
        try:
            curated = discovery_engine.load_curated_feed()
            for job in curated:
                plat_low = job.platform.lower().strip()
                url_low = job.application_url.lower().strip()
                if plat_low in PROHIBITED_SCRAPE_PLATFORMS or "linkedin.com" in url_low or "indeed." in url_low:
                    continue
                raw_candidates.append(job)
        except Exception as exc:
            err = f"Local curated feed error: {exc}"
            logger.warning(err)
            errors_and_unavailable_sources.append(err)

        # Attempt public API discovery (Remotive & Arbeitnow) for each target role
        for role_query in ["AI Engineer", "Machine Learning", "Data Scientist"]:
            try:
                live_jobs = discovery_engine.fetch_public_rss_or_api(role_query=role_query)
                if not live_jobs:
                    errors_and_unavailable_sources.append(
                        f"Public API source for '{role_query}' returned 0 live listings or was unreachable offline."
                    )
                for lj in live_jobs:
                    url_low = lj.application_url.lower()
                    if "linkedin.com" not in url_low and "indeed." not in url_low:
                        raw_candidates.append(lj)
            except Exception as exc:
                errors_and_unavailable_sources.append(
                    f"Public API source error for '{role_query}': {exc} ({traceback.format_exc().splitlines()[-1]})"
                )

        # 3. Filter by target roles, target locations (India, Pune, Remote), remove duplicates and expired listings
        seen_uids = set()
        valid_jobs: List[JobListing] = []
        duplicates_removed = 0
        expired_removed = 0

        for job in raw_candidates:
            uid = db.compute_job_uid(job.company, job.title, job.application_url)
            if uid in seen_uids:
                duplicates_removed += 1
                continue
            seen_uids.add(uid)

            if _is_expired(job.posted_date):
                expired_removed += 1
                continue

            role_match = any(
                r.lower().split()[0] in (job.title + " " + job.role_category + " " + job.description).lower()
                for r in TARGET_DAILY_ROLES
            )
            loc_match = any(loc.lower() in job.location.lower() for loc in TARGET_DAILY_LOCATIONS)

            if role_match and loc_match:
                job_id, _ = db.upsert_job_listing(job)
                saved_job = db.get_job_by_id(job_id)
                if saved_job:
                    valid_jobs.append(saved_job)

        # 4. Compare opportunities against approved resume profile & rank all eligible opportunities
        evaluated_items: List[Dict[str, Any]] = []
        for job in valid_jobs:
            match = ai_engine.evaluate_job_compatibility(active_resume, job)
            db.save_job_match(match)
            evaluated_items.append(
                {
                    "job_id": job.id,
                    "company": job.company,
                    "role": job.title,
                    "role_category": job.role_category,
                    "location": job.location,
                    "stipend": job.stipend or "Not Disclosed",
                    "platform": job.platform,
                    "match_score": match.overall_score,
                    "skill_score": match.skill_score,
                    "semantic_score": match.semantic_score,
                    "matched_skills": match.matched_skills,
                    "missing_skills": match.missing_skills,
                    "recommendation": match.recommendation,
                    "application_url": job.application_url,
                    "source_url": job.source_url or job.application_url,
                    "is_verified_source": job.is_verified_source,
                    "verification_status": job.verification_status,
                    "posted_date": job.posted_date,
                }
            )

        evaluated_items.sort(key=lambda x: x["match_score"], reverse=True)
        top_20_opportunities = evaluated_items[:top_k]

        verified_opportunities_count = sum(1 for item in evaluated_items if item.get("is_verified_source"))
        matching_opportunities_count = sum(1 for item in evaluated_items if item.get("match_score", 0) >= 60.0)

        # 5. Prepare customized cover letters and application answers for the best unapplied matches
        # CRITICAL FIX: Scan across ALL ranked opportunities (preferring verified sources first, then highest match score)
        # rather than only [:5], so if the user already applied to ranks #1..#5 yesterday, ranks #6..#10 are prepared today!
        existing_pending = {d["job_id"]: d for d in db.get_drafts(status_filter="Pending Approval")}
        existing_all_drafts = {d["job_id"]: d for d in db.get_drafts()}

        prepared_draft_summaries: List[Dict[str, Any]] = []
        # Sort candidate pool for draft generation: verified sources first, then highest match score
        draft_candidates = sorted(
            evaluated_items,
            key=lambda x: (1 if x.get("is_verified_source") else 0, x["match_score"]),
            reverse=True,
        )

        for item in draft_candidates:
            if len(prepared_draft_summaries) >= prepare_top_n_drafts:
                break
            jid = item["job_id"]

            # Skip if already submitted or rejected
            if db.has_already_applied(jid, item["company"], item["role"], item["application_url"]):
                continue
            prev_draft = existing_all_drafts.get(jid)
            if prev_draft and prev_draft["status"] in ("Approved & Submitted", "Manually Submitted", "Rejected"):
                continue

            job_obj = db.get_job_by_id(jid)
            if not job_obj:
                continue

            cover_letter = ai_engine.generate_cover_letter(active_resume, job_obj)
            form_answers = ai_engine.prepare_form_answers(active_resume, job_obj, cover_letter)

            draft = ApplicationDraft(
                job_id=jid,
                resume_id=active_resume.id,
                cover_letter=cover_letter,
                form_Payload=form_answers,
                resume_file_path=active_resume.file_path,
                automation_status=(
                    f"Prepared by Daily Automation ({'Verified Source' if job_obj.is_verified_source else 'Demo Portal'} — Awaiting Human Approval)"
                ),
                status="Pending Approval",
            )
            draft_id = db.save_application_draft(draft)
            is_newly_queued = jid not in existing_pending
            prepared_draft_summaries.append(
                {
                    "draft_id": draft_id,
                    "job_id": jid,
                    "company": item["company"],
                    "role": item["role"],
                    "platform": item["platform"],
                    "application_url": item["application_url"],
                    "is_verified_source": item["is_verified_source"],
                    "match_score": item["match_score"],
                    "is_new_draft": is_newly_queued,
                    "status": "Pending Approval (Never Auto-Submitted)",
                }
            )

        total_pending_in_approval_center = len(db.get_drafts(status_filter="Pending Approval"))

        completion_dt = datetime.now()
        completion_time_str = completion_dt.strftime("%Y-%m-%d %H:%M:%S IST")
        duration_sec = round((completion_dt - start_dt).total_seconds(), 2)

        # 6. Send Task 5 Daily Run Summary Email Notification
        email_result: Dict[str, Any] = {}
        try:
            from src.email_notifications import EmailNotificationService

            email_svc = EmailNotificationService(db=db, settings=settings)
            email_result = email_svc.send_daily_run_summary_email(
                jobs_discovered=len(valid_jobs),
                verified_opportunities=verified_opportunities_count,
                matching_opportunities=matching_opportunities_count,
                drafts_prepared_this_run=len(prepared_draft_summaries),
                total_awaiting_approval=total_pending_in_approval_center,
                execution_status=execution_status,
                start_time=start_time_str,
                completion_time=completion_time_str,
                dashboard_url="http://localhost:8501",
                errors=errors_and_unavailable_sources,
            )
        except Exception as exc:
            err_em = f"Daily summary email notification error: {exc}"
            logger.warning(err_em)
            errors_and_unavailable_sources.append(err_em)

        # 7. Update local internship discovery report (.md and .json)
        report_payload = {
            "generated_at": completion_time_str,
            "start_time": start_time_str,
            "completion_time": completion_time_str,
            "duration_seconds": duration_sec,
            "execution_status": execution_status,
            "active_resume_profile": active_resume.full_name,
            "summary": {
                "valid_opportunities_evaluated": len(valid_jobs),
                "verified_opportunities_count": verified_opportunities_count,
                "matching_opportunities_count": matching_opportunities_count,
                "duplicates_removed": duplicates_removed,
                "expired_removed": expired_removed,
                "top_ranked_count": len(top_20_opportunities),
                "applications_prepared_for_approval": len(prepared_draft_summaries),
                "total_awaiting_approval_in_center": total_pending_in_approval_center,
                "auto_submitted_count": 0,
                "email_notification_status": email_result.get("delivery_status", "N/A"),
            },
            "top_20_opportunities": top_20_opportunities,
            "prepared_application_drafts": prepared_draft_summaries,
            "errors_and_unavailable_sources": errors_and_unavailable_sources,
        }

        REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_JSON_PATH.write_text(json.dumps(report_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        md_lines = [
            "# 📊 Daily AI Internship Discovery & Matching Report",
            "",
            f"- **Execution Status:** `{execution_status}`",
            f"- **Start Time:** `{start_time_str}`",
            f"- **Completion Time:** `{completion_time_str}` (`{duration_sec}s`)",
            f"- **Approved Resume Profile:** `{active_resume.full_name}` (`{active_resume.email}`)",
            "- **Target Roles:** AI Engineer, Agentic AI, Generative AI, Machine Learning, Data Science",
            "- **Target Locations:** India, Pune, Remote",
            "- **Compliance Policy:** Permitted public sources & official company career pages only (LinkedIn & Indeed scraping/automation disabled).",
            "- **Safety Guarantee:** `0` applications submitted automatically. All prepared applications await your explicit sign-off in the Streamlit Approval Center.",
            "",
            "## 📈 Pipeline Execution Summary",
            "",
            f"- **Total Permitted Opportunities Discovered / Evaluated:** {len(valid_jobs)}",
            f"- **Verified Source Opportunities:** {verified_opportunities_count}",
            f"- **Matching Opportunities (≥60% Match):** {matching_opportunities_count}",
            f"- **Duplicates Removed:** {duplicates_removed}",
            f"- **Expired Listings Removed:** {expired_removed}",
            f"- **Top Ranked Opportunities Listed:** {len(top_20_opportunities)}",
            f"- **Application Drafts Prepared This Run:** {len(prepared_draft_summaries)}",
            f"- **Total Drafts Currently Awaiting Approval in Approval Center:** {total_pending_in_approval_center}",
            f"- **Summary Email Notification Status:** `{email_result.get('delivery_status', 'N/A')}`",
            "",
            "## 🏆 Top Ranked Internship Opportunities (Up to 20)",
            "",
            "| Rank | Company | Role | Location | Stipend | Match Score | Source Verification | Application URL |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]

        for idx, opp in enumerate(top_20_opportunities, start=1):
            ver_badge = "✅ Verified Source" if opp.get("is_verified_source") else "⚠️ Unverified / Demo Sandbox"
            md_lines.append(
                f"| {idx} | **{opp['company']}** | {opp['role']} | {opp['location']} | "
                f"{opp['stipend']} | **{opp['match_score']}%** | {ver_badge} (`{opp.get('verification_status', '')}`) | "
                f"[Apply Link]({opp['application_url']}) |"
            )

        md_lines.extend(
            [
                "",
                "## ✉️ Prepared Application Drafts (Queued in Approval Center)",
                "",
            ]
        )
        if prepared_draft_summaries:
            for d in prepared_draft_summaries:
                ver_tag = "✅ Verified Source" if d.get("is_verified_source") else "⚠️ Demo Portal"
                md_lines.append(
                    f"- **Draft #{d['draft_id']}** — **{d['role']}** at **{d['company']}** "
                    f"(Match: `{d['match_score']}%` | {ver_tag}) — *{d['status']}*"
                )
        else:
            md_lines.append("- No new qualifying unapplied opportunities remained to prepare.")

        md_lines.extend(
            [
                "",
                "## ⚠️ Source Diagnostics & Unavailable Sources Report",
                "",
            ]
        )
        if errors_and_unavailable_sources:
            for err in errors_and_unavailable_sources:
                md_lines.append(f"- {err}")
        else:
            md_lines.append("- All configured public sources and local career feeds responded normally.")

        REPORT_MD_PATH.write_text("\n".join(md_lines), encoding="utf-8")
        logger.info("Updated daily internship discovery report at %s", REPORT_MD_PATH)
        _append_scheduler_log(
            f"COMPLETED | status={execution_status} | discovered={len(valid_jobs)} | verified={verified_opportunities_count} | "
            f"matching={matching_opportunities_count} | drafts_prepared={len(prepared_draft_summaries)} | "
            f"awaiting_approval={total_pending_in_approval_center} | duration={duration_sec}s"
        )

        return {
            "success": True,
            "execution_status": execution_status,
            "start_time": start_time_str,
            "completion_time": completion_time_str,
            "duration_seconds": duration_sec,
            "report_md_path": str(REPORT_MD_PATH),
            "report_json_path": str(REPORT_JSON_PATH),
            "summary": report_payload["summary"],
            "top_20_opportunities": top_20_opportunities,
            "prepared_drafts": prepared_draft_summaries,
            "email_notification": email_result,
            "errors": errors_and_unavailable_sources,
        }
    except Exception as fatal_exc:
        tb_str = traceback.format_exc()
        logger.error("Fatal error in daily discovery pipeline: %s\n%s", fatal_exc, tb_str)
        _append_scheduler_log(f"FATAL_ERROR | {fatal_exc} | {tb_str.splitlines()[-1]}")
        return {
            "success": False,
            "execution_status": "FAILED_EXCEPTION",
            "start_time": start_time_str,
            "completion_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
            "errors": [str(fatal_exc), tb_str],
        }
    finally:
        _release_execution_lock()


if __name__ == "__main__":
    result = run_daily_discovery_pipeline()
    print(json.dumps(result.get("summary", result), indent=2))
    if result.get("report_md_path"):
        print(f"Report written to: {result['report_md_path']}")
