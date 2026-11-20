"""SQLite database repository for AI Internship Application Agent.

Manages tables:
1. resume_profiles
2. job_listings
3. job_matches
4. application_drafts
5. applications
6. approval_history

Enforces duplicate prevention across job listings and submitted applications.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.logger import get_logger
from src.models import (
    ApplicationDraft,
    ApplicationRecord,
    ApprovalHistoryItem,
    EducationItem,
    ExperienceItem,
    JobListing,
    JobMatch,
    ProjectItem,
    ResumeProfile,
)

logger = get_logger("database")


class DatabaseManager:
    """Thread-safe SQLite database access layer."""

    def __init__(self, db_path: str = "data/internship_agent.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        """Create all 6 required tables if they do not exist."""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # 1. Resume profiles
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS resume_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_name TEXT NOT NULL,
                    full_name TEXT DEFAULT '',
                    email TEXT DEFAULT '',
                    phone TEXT DEFAULT '',
                    location TEXT DEFAULT '',
                    linkedin_url TEXT DEFAULT '',
                    github_url TEXT DEFAULT '',
                    portfolio_url TEXT DEFAULT '',
                    summary TEXT DEFAULT '',
                    education_json TEXT DEFAULT '[]',
                    skills_json TEXT DEFAULT '[]',
                    projects_json TEXT DEFAULT '[]',
                    experience_json TEXT DEFAULT '[]',
                    raw_text TEXT DEFAULT '',
                    file_path TEXT DEFAULT '',
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            # 2. Job listings (unique job_uid or unique company+title+application_url)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS job_listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_uid TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT DEFAULT 'Remote',
                    stipend TEXT DEFAULT 'Not Disclosed',
                    platform TEXT DEFAULT 'Official Career Page',
                    role_category TEXT DEFAULT 'AI Engineer',
                    application_url TEXT NOT NULL,
                    source_url TEXT DEFAULT '',
                    is_verified_source INTEGER DEFAULT 1,
                    verification_status TEXT DEFAULT 'VERIFIED_PUBLIC_SOURCE',
                    description TEXT DEFAULT '',
                    required_skills_json TEXT DEFAULT '[]',
                    posted_date TEXT DEFAULT '',
                    is_saved INTEGER DEFAULT 1,
                    discovered_at TEXT NOT NULL
                );
                """
            )
            # Safe schema migration for existing job_listings table
            existing_cols = {
                row["name"] for row in cursor.execute("PRAGMA table_info(job_listings)").fetchall()
            }
            if "source_url" not in existing_cols:
                cursor.execute("ALTER TABLE job_listings ADD COLUMN source_url TEXT DEFAULT '';")
            if "is_verified_source" not in existing_cols:
                cursor.execute("ALTER TABLE job_listings ADD COLUMN is_verified_source INTEGER DEFAULT 1;")
            if "verification_status" not in existing_cols:
                cursor.execute(
                    "ALTER TABLE job_listings ADD COLUMN verification_status TEXT DEFAULT 'VERIFIED_PUBLIC_SOURCE';"
                )

            # 3. Job matches
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS job_matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    resume_id INTEGER NOT NULL,
                    overall_score REAL NOT NULL,
                    skill_score REAL NOT NULL,
                    semantic_score REAL NOT NULL,
                    role_alignment_score REAL NOT NULL,
                    matched_skills_json TEXT DEFAULT '[]',
                    missing_skills_json TEXT DEFAULT '[]',
                    explanation TEXT DEFAULT '',
                    recommendation TEXT DEFAULT '',
                    evaluated_at TEXT NOT NULL,
                    UNIQUE(job_id, resume_id),
                    FOREIGN KEY(job_id) REFERENCES job_listings(id) ON DELETE CASCADE,
                    FOREIGN KEY(resume_id) REFERENCES resume_profiles(id) ON DELETE CASCADE
                );
                """
            )

            # 4. Application drafts
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS application_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER UNIQUE NOT NULL,
                    resume_id INTEGER NOT NULL,
                    cover_letter TEXT DEFAULT '',
                    form_payload_json TEXT DEFAULT '{}',
                    resume_file_path TEXT DEFAULT '',
                    automation_status TEXT DEFAULT 'Draft Saved',
                    screenshot_path TEXT DEFAULT '',
                    detected_fields_json TEXT DEFAULT '[]',
                    status TEXT DEFAULT 'Pending Approval',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES job_listings(id) ON DELETE CASCADE,
                    FOREIGN KEY(resume_id) REFERENCES resume_profiles(id) ON DELETE CASCADE
                );
                """
            )

            # 5. Applications (prevents duplicate applications per job_id or company+role+url)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER UNIQUE NOT NULL,
                    draft_id INTEGER,
                    resume_id INTEGER NOT NULL,
                    company TEXT NOT NULL,
                    role TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    application_url TEXT NOT NULL,
                    applied_date TEXT NOT NULL,
                    status TEXT DEFAULT 'Submitted',
                    follow_up_date TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    screenshot_path TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(company, role, application_url),
                    FOREIGN KEY(job_id) REFERENCES job_listings(id) ON DELETE CASCADE
                );
                """
            )

            # 6. Approval history
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draft_id INTEGER NOT NULL,
                    job_id INTEGER NOT NULL,
                    company TEXT NOT NULL,
                    role TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reviewer_notes TEXT DEFAULT '',
                    confirmed_checkbox INTEGER DEFAULT 1,
                    form_snapshot_json TEXT DEFAULT '{}',
                    resume_path TEXT DEFAULT '',
                    timestamp TEXT NOT NULL
                );
                """
            )

            # 7. Email notification logs (prevents duplicate emails via unique dedup_key)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS email_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dedup_key TEXT UNIQUE NOT NULL,
                    event_type TEXT NOT NULL,
                    recipient_email TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    company TEXT DEFAULT '',
                    role TEXT DEFAULT '',
                    tracking_id TEXT DEFAULT '',
                    delivery_status TEXT NOT NULL,
                    attempts INTEGER DEFAULT 1,
                    error_message TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.commit()

    @staticmethod
    def compute_job_uid(company: str, title: str, url: str) -> str:
        """Compute deterministic hash for duplicate job detection."""
        norm = f"{company.strip().lower()}|{title.strip().lower()}|{url.strip().lower()}"
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:24]

    # ---------------- RESUME PROFILES ---------------- #

    def save_resume_profile(self, profile: ResumeProfile) -> int:
        """Insert or update a resume profile and mark it active."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        edu_json = json.dumps([e.model_dump() for e in profile.education])
        skills_json = json.dumps(profile.skills)
        proj_json = json.dumps([p.model_dump() for p in profile.projects])
        exp_json = json.dumps([x.model_dump() for x in profile.experience])

        with self._get_conn() as conn:
            cur = conn.cursor()
            if profile.is_active:
                cur.execute("UPDATE resume_profiles SET is_active = 0;")

            if profile.id:
                cur.execute(
                    """
                    UPDATE resume_profiles
                    SET profile_name=?, full_name=?, email=?, phone=?, location=?,
                        linkedin_url=?, github_url=?, portfolio_url=?, summary=?,
                        education_json=?, skills_json=?, projects_json=?, experience_json=?,
                        raw_text=?, file_path=?, is_active=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        profile.profile_name,
                        profile.full_name,
                        profile.email,
                        profile.phone,
                        profile.location,
                        profile.linkedin_url,
                        profile.github_url,
                        profile.portfolio_url,
                        profile.summary,
                        edu_json,
                        skills_json,
                        proj_json,
                        exp_json,
                        profile.raw_text,
                        profile.file_path,
                        1 if profile.is_active else 0,
                        now,
                        profile.id,
                    ),
                )
                resume_id = profile.id
            else:
                cur.execute(
                    """
                    INSERT INTO resume_profiles (
                        profile_name, full_name, email, phone, location,
                        linkedin_url, github_url, portfolio_url, summary,
                        education_json, skills_json, projects_json, experience_json,
                        raw_text, file_path, is_active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile.profile_name,
                        profile.full_name,
                        profile.email,
                        profile.phone,
                        profile.location,
                        profile.linkedin_url,
                        profile.github_url,
                        profile.portfolio_url,
                        profile.summary,
                        edu_json,
                        skills_json,
                        proj_json,
                        exp_json,
                        profile.raw_text,
                        profile.file_path,
                        1 if profile.is_active else 0,
                        now,
                        now,
                    ),
                )
                resume_id = int(cur.lastrowid)
            conn.commit()
            logger.info("Saved resume profile ID=%s (%s)", resume_id, profile.full_name)
            return resume_id

    def _row_to_resume(self, row: sqlite3.Row) -> ResumeProfile:
        return ResumeProfile(
            id=row["id"],
            profile_name=row["profile_name"],
            full_name=row["full_name"],
            email=row["email"],
            phone=row["phone"],
            location=row["location"],
            linkedin_url=row["linkedin_url"],
            github_url=row["github_url"],
            portfolio_url=row["portfolio_url"],
            summary=row["summary"],
            education=[EducationItem(**e) for e in json.loads(row["education_json"] or "[]")],
            skills=json.loads(row["skills_json"] or "[]"),
            projects=[ProjectItem(**p) for p in json.loads(row["projects_json"] or "[]")],
            experience=[ExperienceItem(**x) for x in json.loads(row["experience_json"] or "[]")],
            raw_text=row["raw_text"],
            file_path=row["file_path"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_active_resume(self) -> Optional[ResumeProfile]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM resume_profiles WHERE is_active = 1 ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT * FROM resume_profiles ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
            return self._row_to_resume(row) if row else None

    def get_all_resumes(self) -> List[ResumeProfile]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM resume_profiles ORDER BY updated_at DESC").fetchall()
            return [self._row_to_resume(r) for r in rows]

    # ---------------- JOB LISTINGS ---------------- #

    def upsert_job_listing(self, job: JobListing) -> Tuple[int, bool]:
        """Insert a job listing or return existing ID if already present. Returns (job_id, is_new)."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        uid = job.job_uid or self.compute_job_uid(job.company, job.title, job.application_url)
        skills_json = json.dumps(job.required_skills)
        src_url = job.source_url or job.application_url

        with self._get_conn() as conn:
            cur = conn.cursor()
            existing = cur.execute("SELECT id FROM job_listings WHERE job_uid = ?", (uid,)).fetchone()
            if existing:
                job_id = int(existing["id"])
                cur.execute(
                    """
                    UPDATE job_listings
                    SET stipend=?, description=?, required_skills_json=?, is_saved=?,
                        source_url=?, is_verified_source=?, verification_status=?
                    WHERE id=?
                    """,
                    (
                        job.stipend,
                        job.description,
                        skills_json,
                        1 if job.is_saved else 0,
                        src_url,
                        1 if job.is_verified_source else 0,
                        job.verification_status,
                        job_id,
                    ),
                )
                conn.commit()
                return job_id, False

            cur.execute(
                """
                INSERT INTO job_listings (
                    job_uid, title, company, location, stipend, platform,
                    role_category, application_url, source_url, is_verified_source,
                    verification_status, description, required_skills_json,
                    posted_date, is_saved, discovered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    job.title,
                    job.company,
                    job.location,
                    job.stipend,
                    job.platform,
                    job.role_category,
                    job.application_url,
                    src_url,
                    1 if job.is_verified_source else 0,
                    job.verification_status,
                    job.description,
                    skills_json,
                    job.posted_date,
                    1 if job.is_saved else 0,
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid), True

    def _row_to_job(self, row: sqlite3.Row) -> JobListing:
        keys = row.keys()
        return JobListing(
            id=row["id"],
            job_uid=row["job_uid"],
            title=row["title"],
            company=row["company"],
            location=row["location"],
            stipend=row["stipend"],
            platform=row["platform"],
            role_category=row["role_category"],
            application_url=row["application_url"],
            source_url=row["source_url"] if "source_url" in keys and row["source_url"] else row["application_url"],
            is_verified_source=bool(row["is_verified_source"]) if "is_verified_source" in keys else True,
            verification_status=(
                row["verification_status"]
                if "verification_status" in keys and row["verification_status"]
                else "VERIFIED_PUBLIC_SOURCE"
            ),
            description=row["description"],
            required_skills=json.loads(row["required_skills_json"] or "[]"),
            posted_date=row["posted_date"],
            is_saved=bool(row["is_saved"]),
            discovered_at=row["discovered_at"],
        )

    def get_job_listings(
        self,
        role_filter: Optional[str] = None,
        location_filter: Optional[str] = None,
        platform_filter: Optional[str] = None,
        saved_only: bool = False,
    ) -> List[JobListing]:
        query = "SELECT * FROM job_listings WHERE 1=1"
        params: List[Any] = []

        if role_filter and role_filter != "All":
            query += " AND (LOWER(role_category) LIKE ? OR LOWER(title) LIKE ?)"
            params.extend([f"%{role_filter.lower()}%", f"%{role_filter.lower()}%"])

        if location_filter and location_filter != "All":
            query += " AND LOWER(location) LIKE ?"
            params.append(f"%{location_filter.lower()}%")

        if platform_filter and platform_filter != "All":
            query += " AND LOWER(platform) LIKE ?"
            params.append(f"%{platform_filter.lower()}%")

        if saved_only:
            query += " AND is_saved = 1"

        query += " ORDER BY id DESC"

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_job(r) for r in rows]

    def get_job_by_id(self, job_id: int) -> Optional[JobListing]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM job_listings WHERE id = ?", (job_id,)).fetchone()
            return self._row_to_job(row) if row else None

    def set_job_saved(self, job_id: int, is_saved: bool = True) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE job_listings SET is_saved = ? WHERE id = ?",
                (1 if is_saved else 0, job_id),
            )
            conn.commit()

    # ---------------- JOB MATCHES ---------------- #

    def save_job_match(self, match: JobMatch) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO job_matches (
                    job_id, resume_id, overall_score, skill_score, semantic_score,
                    role_alignment_score, matched_skills_json, missing_skills_json,
                    explanation, recommendation, evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, resume_id) DO UPDATE SET
                    overall_score=excluded.overall_score,
                    skill_score=excluded.skill_score,
                    semantic_score=excluded.semantic_score,
                    role_alignment_score=excluded.role_alignment_score,
                    matched_skills_json=excluded.matched_skills_json,
                    missing_skills_json=excluded.missing_skills_json,
                    explanation=excluded.explanation,
                    recommendation=excluded.recommendation,
                    evaluated_at=excluded.evaluated_at
                """,
                (
                    match.job_id,
                    match.resume_id,
                    match.overall_score,
                    match.skill_score,
                    match.semantic_score,
                    match.role_alignment_score,
                    json.dumps(match.matched_skills),
                    json.dumps(match.missing_skills),
                    match.explanation,
                    match.recommendation,
                    now,
                ),
            )
            conn.commit()
            row = cur.execute(
                "SELECT id FROM job_matches WHERE job_id=? AND resume_id=?",
                (match.job_id, match.resume_id),
            ).fetchone()
            return int(row["id"]) if row else 0

    def get_ranked_matches(self, resume_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return joined job + match records ordered by overall_score descending."""
        query = """
            SELECT
                m.*,
                j.title, j.company, j.location, j.stipend, j.platform,
                j.role_category, j.application_url, j.source_url,
                j.is_verified_source, j.verification_status,
                j.description, j.required_skills_json
            FROM job_matches m
            JOIN job_listings j ON m.job_id = j.id
        """
        params: List[Any] = []
        if resume_id is not None:
            query += " WHERE m.resume_id = ?"
            params.append(resume_id)
        query += " ORDER BY m.overall_score DESC"

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                keys = r.keys()
                results.append(
                    {
                        "match_id": r["id"],
                        "job_id": r["job_id"],
                        "resume_id": r["resume_id"],
                        "title": r["title"],
                        "company": r["company"],
                        "location": r["location"],
                        "stipend": r["stipend"],
                        "platform": r["platform"],
                        "role_category": r["role_category"],
                        "application_url": r["application_url"],
                        "source_url": r["source_url"] if "source_url" in keys and r["source_url"] else r["application_url"],
                        "is_verified_source": bool(r["is_verified_source"]) if "is_verified_source" in keys else True,
                        "verification_status": (
                            r["verification_status"]
                            if "verification_status" in keys and r["verification_status"]
                            else "VERIFIED_PUBLIC_SOURCE"
                        ),
                        "description": r["description"],
                        "overall_score": round(float(r["overall_score"]), 1),
                        "skill_score": round(float(r["skill_score"]), 1),
                        "semantic_score": round(float(r["semantic_score"]), 1),
                        "role_alignment_score": round(float(r["role_alignment_score"]), 1),
                        "matched_skills": json.loads(r["matched_skills_json"] or "[]"),
                        "missing_skills": json.loads(r["missing_skills_json"] or "[]"),
                        "required_skills": json.loads(r["required_skills_json"] or "[]"),
                        "explanation": r["explanation"],
                        "recommendation": r["recommendation"],
                        "evaluated_at": r["evaluated_at"],
                    }
                )
            return results

    # ---------------- APPLICATION DRAFTS & DUPLICATE PREVENTION ---------------- #

    def has_already_applied(self, job_id: int, company: str = "", role: str = "", url: str = "") -> bool:
        """Check whether an application has already been submitted for this job."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT id FROM applications WHERE job_id = ?", (job_id,)).fetchone()
            if row:
                return True
            if company and role and url:
                row2 = conn.execute(
                    """
                    SELECT id FROM applications
                    WHERE LOWER(company)=? AND LOWER(role)=? AND LOWER(application_url)=?
                    """,
                    (company.strip().lower(), role.strip().lower(), url.strip().lower()),
                ).fetchone()
                if row2:
                    return True
            return False

    def save_application_draft(self, draft: ApplicationDraft) -> int:
        """Create or update an application draft for a job. Refuses if already submitted."""
        if self.has_already_applied(draft.job_id):
            raise ValueError(f"Duplicate prevention: An application for job_id={draft.job_id} was already submitted.")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO application_drafts (
                    job_id, resume_id, cover_letter, form_payload_json,
                    resume_file_path, automation_status, screenshot_path,
                    detected_fields_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    resume_id=excluded.resume_id,
                    cover_letter=excluded.cover_letter,
                    form_payload_json=excluded.form_payload_json,
                    resume_file_path=excluded.resume_file_path,
                    automation_status=excluded.automation_status,
                    screenshot_path=excluded.screenshot_path,
                    detected_fields_json=excluded.detected_fields_json,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    draft.job_id,
                    draft.resume_id,
                    draft.cover_letter,
                    json.dumps(draft.form_Payload),
                    draft.resume_file_path,
                    draft.automation_status,
                    draft.screenshot_path,
                    json.dumps(draft.detected_fields),
                    draft.status,
                    now,
                    now,
                ),
            )
            conn.commit()
            row = cur.execute("SELECT id FROM application_drafts WHERE job_id = ?", (draft.job_id,)).fetchone()
            return int(row["id"]) if row else 0

    def get_drafts(self, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        query = """
            SELECT
                d.*,
                j.title, j.company, j.location, j.stipend, j.platform, j.application_url
            FROM application_drafts d
            JOIN job_listings j ON d.job_id = j.id
        """
        params: List[Any] = []
        if status_filter:
            query += " WHERE d.status = ?"
            params.append(status_filter)
        query += " ORDER BY d.updated_at DESC"

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            out = []
            for r in rows:
                out.append(
                    {
                        "id": r["id"],
                        "job_id": r["job_id"],
                        "resume_id": r["resume_id"],
                        "title": r["title"],
                        "company": r["company"],
                        "location": r["location"],
                        "stipend": r["stipend"],
                        "platform": r["platform"],
                        "application_url": r["application_url"],
                        "cover_letter": r["cover_letter"],
                        "form_payload": json.loads(r["form_payload_json"] or "{}"),
                        "resume_file_path": r["resume_file_path"],
                        "automation_status": r["automation_status"],
                        "screenshot_path": r["screenshot_path"],
                        "detected_fields": json.loads(r["detected_fields_json"] or "[]"),
                        "status": r["status"],
                        "created_at": r["created_at"],
                        "updated_at": r["updated_at"],
                    }
                )
            return out

    def get_draft_by_job_id(self, job_id: int) -> Optional[Dict[str, Any]]:
        drafts = self.get_drafts()
        for d in drafts:
            if d["job_id"] == job_id:
                return d
        return None

    def get_draft_by_id(self, draft_id: int) -> Optional[Dict[str, Any]]:
        drafts = self.get_drafts()
        for d in drafts:
            if d["id"] == draft_id:
                return d
        return None

    # ---------------- APPROVAL WORKFLOW & APPLICATIONS TRACKER ---------------- #

    def approve_and_record_submission(
        self,
        draft_id: int,
        reviewer_notes: str = "",
        confirmed_checkbox: bool = True,
        final_screenshot_path: str = "",
        portal_confirmed: bool = True,
    ) -> int:
        """Record human approval in approval_history, mark draft Approved & Submitted, and create application entry."""
        if not confirmed_checkbox:
            raise ValueError("Explicit human confirmation is required before submitting any application.")

        draft = self.get_draft_by_id(draft_id)
        if not draft:
            raise ValueError(f"Application draft ID={draft_id} not found.")

        if self.has_already_applied(
            draft["job_id"], draft["company"], draft["title"], draft["application_url"]
        ):
            raise ValueError(
                f"Duplicate application prevented: Already applied to {draft['title']} at {draft['company']}."
            )

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today = datetime.now().strftime("%Y-%m-%d")
        follow_up = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        screenshot = final_screenshot_path or draft["screenshot_path"]
        final_app_status = "Submitted" if portal_confirmed else "Pending Verification"

        with self._get_conn() as conn:
            cur = conn.cursor()

            # 1. Update draft status
            cur.execute(
                """
                UPDATE application_drafts
                SET status = 'Approved & Submitted',
                    automation_status = ?,
                    screenshot_path = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    "Submitted with Human Approval (Portal Confirmed)"
                    if portal_confirmed
                    else "Approved (Pending Portal Verification)",
                    screenshot,
                    now,
                    draft_id,
                ),
            )

            # 2. Insert approval_history audit record
            cur.execute(
                """
                INSERT INTO approval_history (
                    draft_id, job_id, company, role, decision, reviewer_notes,
                    confirmed_checkbox, form_snapshot_json, resume_path, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    draft["job_id"],
                    draft["company"],
                    draft["title"],
                    "APPROVED_AND_SUBMITTED" if portal_confirmed else "APPROVED_PENDING_VERIFICATION",
                    reviewer_notes,
                    1,
                    json.dumps(draft["form_payload"]),
                    draft["resume_file_path"],
                    now,
                ),
            )

            # 3. Insert into applications tracker
            cur.execute(
                """
                INSERT INTO applications (
                    job_id, draft_id, resume_id, company, role, platform,
                    application_url, applied_date, status, follow_up_date,
                    notes, screenshot_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft["job_id"],
                    draft_id,
                    draft["resume_id"],
                    draft["company"],
                    draft["title"],
                    draft["platform"],
                    draft["application_url"],
                    today,
                    final_app_status,
                    follow_up,
                    reviewer_notes or "Approved & submitted via Approval Center.",
                    screenshot,
                    now,
                ),
            )
            app_id = int(cur.lastrowid)
            conn.commit()
            logger.info("Application approved and submitted: app_id=%s (%s - %s)", app_id, draft["company"], draft["title"])

        # Trigger submission confirmation email ONLY after portal_confirmed check
        try:
            from src.email_notifications import EmailNotificationService

            email_svc = EmailNotificationService(db=self)
            email_svc.send_submission_confirmation_email(
                company=draft["company"],
                role=draft["title"],
                platform=draft["platform"],
                application_url=draft["application_url"],
                resume_used=draft["resume_file_path"],
                application_status=final_app_status,
                tracking_id=app_id,
                submission_mode="AUTOMATED",
                portal_confirmed=portal_confirmed,
                explicit_manual_mark=False,
                submission_datetime=now,
            )
        except Exception as exc:
            logger.warning("Email notification dispatch error after automated submission: %s", exc)

        return app_id

    def mark_as_manually_submitted(
        self,
        draft_id: int,
        reviewer_notes: str = "",
        confirmed_checkbox: bool = True,
        submission_date: Optional[str] = None,
    ) -> int:
        """Record that the user manually submitted an application (e.g., on LinkedIn, Indeed, or a restricted portal).

        Strictly updates SQLite status, records the submission date, prevents duplicate submissions,
        and writes an audit log entry (`MANUALLY_SUBMITTED`). Never opens or submits any browser form.
        """
        if not confirmed_checkbox:
            raise ValueError("Explicit confirmation is required before marking an application as manually submitted.")

        draft = self.get_draft_by_id(draft_id)
        if not draft:
            raise ValueError(f"Application draft ID={draft_id} not found.")

        if self.has_already_applied(
            draft["job_id"], draft["company"], draft["title"], draft["application_url"]
        ):
            raise ValueError(
                f"Duplicate submission prevented: An application for {draft['title']} at {draft['company']} is already recorded."
            )

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        applied_day = (submission_date or datetime.now().strftime("%Y-%m-%d")).strip()
        follow_up = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

        with self._get_conn() as conn:
            cur = conn.cursor()

            # 1. Update draft status in application_drafts (does not alter any existing applications rows)
            cur.execute(
                """
                UPDATE application_drafts
                SET status = 'Manually Submitted',
                    automation_status = 'Manually Submitted by User (No Browser Re-Open)',
                    updated_at = ?
                WHERE id = ?
                """,
                (now, draft_id),
            )

            # 2. Insert immutable audit log entry in approval_history
            cur.execute(
                """
                INSERT INTO approval_history (
                    draft_id, job_id, company, role, decision, reviewer_notes,
                    confirmed_checkbox, form_snapshot_json, resume_path, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    draft["job_id"],
                    draft["company"],
                    draft["title"],
                    "MANUALLY_SUBMITTED",
                    reviewer_notes or f"Marked as manually submitted on {applied_day}.",
                    1,
                    json.dumps(draft["form_payload"]),
                    draft["resume_file_path"],
                    now,
                ),
            )

            # 3. Insert new tracked record into applications table
            cur.execute(
                """
                INSERT INTO applications (
                    job_id, draft_id, resume_id, company, role, platform,
                    application_url, applied_date, status, follow_up_date,
                    notes, screenshot_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft["job_id"],
                    draft_id,
                    draft["resume_id"],
                    draft["company"],
                    draft["title"],
                    draft["platform"],
                    draft["application_url"],
                    applied_day,
                    "Submitted",
                    follow_up,
                    reviewer_notes or f"Manually submitted by user on {draft['platform']} ({applied_day}).",
                    draft["screenshot_path"],
                    now,
                ),
            )
            app_id = int(cur.lastrowid)
            conn.commit()
            logger.info(
                "Application marked as manually submitted (no browser opened): app_id=%s (%s - %s)",
                app_id,
                draft["company"],
                draft["title"],
            )

        # Send manual submission confirmation email ONLY after user explicitly marks as manually submitted
        try:
            from src.email_notifications import EmailNotificationService

            email_svc = EmailNotificationService(db=self)
            email_svc.send_submission_confirmation_email(
                company=draft["company"],
                role=draft["title"],
                platform=draft["platform"],
                application_url=draft["application_url"],
                resume_used=draft["resume_file_path"],
                application_status="Submitted (Manually Submitted by User)",
                tracking_id=app_id,
                submission_mode="MANUAL",
                portal_confirmed=False,
                explicit_manual_mark=True,
                submission_datetime=f"{applied_day} ({now})",
            )
        except Exception as exc:
            logger.warning("Email notification dispatch error after manual submission mark: %s", exc)

        return app_id

    def reject_application_draft(
        self,
        draft_id: int,
        reviewer_notes: str = "",
    ) -> None:
        """Mark draft as Rejected, log in approval_history, and record Rejected status in tracker if desired."""
        draft = self.get_draft_by_id(draft_id)
        if not draft:
            raise ValueError(f"Application draft ID={draft_id} not found.")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today = datetime.now().strftime("%Y-%m-%d")

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE application_drafts
                SET status = 'Rejected',
                    automation_status = 'Rejected by User',
                    updated_at = ?
                WHERE id = ?
                """,
                (now, draft_id),
            )

            cur.execute(
                """
                INSERT INTO approval_history (
                    draft_id, job_id, company, role, decision, reviewer_notes,
                    confirmed_checkbox, form_snapshot_json, resume_path, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    draft["job_id"],
                    draft["company"],
                    draft["title"],
                    "REJECTED",
                    reviewer_notes or "Rejected by user in Approval Center",
                    1,
                    json.dumps(draft["form_payload"]),
                    draft["resume_file_path"],
                    now,
                ),
            )

            # Also track rejected application in applications table if not already present
            existing = cur.execute("SELECT id FROM applications WHERE job_id = ?", (draft["job_id"],)).fetchone()
            if existing:
                cur.execute(
                    "UPDATE applications SET status = 'Rejected', notes = ? WHERE id = ?",
                    (reviewer_notes or "Rejected in Approval Center", existing["id"]),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO applications (
                        job_id, draft_id, resume_id, company, role, platform,
                        application_url, applied_date, status, follow_up_date,
                        notes, screenshot_path, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        draft["job_id"],
                        draft_id,
                        draft["resume_id"],
                        draft["company"],
                        draft["title"],
                        draft["platform"],
                        draft["application_url"],
                        today,
                        "Rejected",
                        "",
                        reviewer_notes or "Rejected in Approval Center.",
                        draft["screenshot_path"],
                        now,
                    ),
                )
            conn.commit()
            logger.info("Application draft ID=%s rejected by user.", draft_id)

    def get_applications(self, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM applications"
        params: List[Any] = []
        if status_filter and status_filter != "All":
            query += " WHERE status = ?"
            params.append(status_filter)
        query += " ORDER BY applied_date DESC, id DESC"

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def update_application_status(
        self, app_id: int, new_status: str, follow_up_date: str = "", notes: str = ""
    ) -> None:
        app_row = None
        with self._get_conn() as conn:
            app_row = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
            conn.execute(
                """
                UPDATE applications
                SET status = ?, follow_up_date = ?, notes = ?
                WHERE id = ?
                """,
                (new_status, follow_up_date, notes, app_id),
            )
            conn.commit()

        if app_row:
            try:
                from src.email_notifications import EmailNotificationService

                email_svc = EmailNotificationService(db=self)
                email_svc.send_status_update_notification(
                    app_id=app_id,
                    company=app_row["company"],
                    role=app_row["role"],
                    new_status=new_status,
                    follow_up_date=follow_up_date,
                    notes=notes,
                )
            except Exception as exc:
                logger.warning("Status update email notification failed: %s", exc)

    def get_approval_history(self) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM approval_history ORDER BY id DESC").fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["form_snapshot"] = json.loads(d.get("form_snapshot_json") or "{}")
                out.append(d)
            return out

    # ---------------- EMAIL NOTIFICATIONS LOGGING & DEDUPLICATION ---------------- #

    def has_notification_been_sent(self, dedup_key: str) -> bool:
        """Return True if a notification with the same dedup_key has already been sent or queued."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id, delivery_status FROM email_notifications WHERE dedup_key = ?",
                (dedup_key,),
            ).fetchone()
            return bool(row and row["delivery_status"] in ("SENT_SMTP", "LOGGED_LOCAL_OUTBOX"))

    def log_email_notification(
        self,
        dedup_key: str,
        event_type: str,
        recipient_email: str,
        subject: str,
        body: str,
        company: str = "",
        role: str = "",
        tracking_id: str = "",
        delivery_status: str = "SENT_SMTP",
        attempts: int = 1,
        error_message: str = "",
    ) -> int:
        """Insert or update an email notification audit log in SQLite."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO email_notifications (
                    dedup_key, event_type, recipient_email, subject, body,
                    company, role, tracking_id, delivery_status, attempts,
                    error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedup_key) DO UPDATE SET
                    delivery_status=excluded.delivery_status,
                    attempts=excluded.attempts,
                    error_message=excluded.error_message
                """,
                (
                    dedup_key,
                    event_type,
                    recipient_email,
                    subject,
                    body,
                    company,
                    role,
                    tracking_id,
                    delivery_status,
                    attempts,
                    error_message,
                    now,
                ),
            )
            conn.commit()
            row = cur.execute(
                "SELECT id FROM email_notifications WHERE dedup_key = ?",
                (dedup_key,),
            ).fetchone()
            return int(row["id"]) if row else 0

    def get_email_notifications(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent email notification logs from SQLite."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM email_notifications ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------------- OVERVIEW METRICS ---------------- #

    def get_overview_metrics(self, relevance_threshold: float = 60.0) -> Dict[str, int]:
        """Compute the 6 key metrics for Page A (Overview)."""
        with self._get_conn() as conn:
            total_discovered = conn.execute("SELECT COUNT(*) AS c FROM job_listings").fetchone()["c"]

            relevant_jobs = conn.execute(
                "SELECT COUNT(DISTINCT job_id) AS c FROM job_matches WHERE overall_score >= ?",
                (relevance_threshold,),
            ).fetchone()["c"]
            if relevant_jobs == 0 and total_discovered > 0:
                # If job matches haven't been run on all, count saved jobs matching target roles
                relevant_jobs = conn.execute(
                    "SELECT COUNT(*) AS c FROM job_listings WHERE is_saved = 1"
                ).fetchone()["c"]

            apps_prepared = conn.execute("SELECT COUNT(*) AS c FROM application_drafts").fetchone()["c"]

            apps_submitted = conn.execute(
                "SELECT COUNT(*) AS c FROM applications WHERE status IN ('Submitted', 'Under Review', 'Interview', 'Offer')"
            ).fetchone()["c"]

            interviews = conn.execute(
                "SELECT COUNT(*) AS c FROM applications WHERE status = 'Interview'"
            ).fetchone()["c"]

            rejected = conn.execute(
                "SELECT COUNT(*) AS c FROM applications WHERE status = 'Rejected'"
            ).fetchone()["c"]

            return {
                "total_discovered": int(total_discovered),
                "relevant_jobs": int(relevant_jobs),
                "applications_prepared": int(apps_prepared),
                "applications_submitted": int(apps_submitted),
                "interviews": int(interviews),
                "rejected_applications": int(rejected),
            }
