"""AI Internship Application Agent - Primary Streamlit Dashboard.
Implements all 8 required pages:
A. Overview
B. Resume Manager
C. Job Discovery
D. AI Job Matching
E. Application Preparation
F. Approval Center
G. Application Tracker
H. Settings
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from src.ai_engine import AIIntelligenceEngine, get_llm_provider
from src.browser_automation import BrowserAutomationEngine
from src.config import (
    AppSettings,
    TARGET_PLATFORMS_DEFAULT,
    TARGET_ROLES_DEFAULT,
    load_settings,
    save_settings,
)
from src.database import DatabaseManager
from src.export_utils import (
    applications_to_dataframe,
    export_applications_to_csv,
    export_applications_to_excel,
)
from src.job_discovery import JobDiscoveryEngine
from src.logger import get_logger
from src.models import (
    ApplicationDraft,
    EducationItem,
    ExperienceItem,
    JobListing,
    ProjectItem,
    ResumeProfile,
)
from src.daily_automation import REPORT_JSON_PATH, REPORT_MD_PATH, run_daily_discovery_pipeline
from src.email_notifications import EmailNotificationService
from src.resume_parser import ResumeParser, SKILL_TAXONOMY, extract_skills_from_text
from src.sample_data import RESUMES_DIR, ensure_sample_environment

logger = get_logger("streamlit_app")

st.set_page_config(
    page_title="AI Internship Application Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for clean metric cards and visual polish
st.markdown(
    """
    <style>
    .metric-card {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 18px 20px;
        color: #f8fafc;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
        margin-bottom: 12px;
    }
    .metric-label {
        font-size: 0.85rem;
        color: #94a3b8;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .metric-value {
        font-size: 2.1rem;
        font-weight: 700;
        color: #38bdf8;
        margin-top: 6px;
    }
    .safety-banner {
        background-color: #064e3b;
        color: #d1fae5;
        padding: 10px 16px;
        border-radius: 8px;
        border-left: 5px solid #10b981;
        font-size: 0.9rem;
        margin-bottom: 16px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_db() -> DatabaseManager:
    settings = load_settings()
    db = DatabaseManager(settings.database_path)
    ensure_sample_environment(db)
    return db


db = get_db()
settings = load_settings()
ai_engine = AIIntelligenceEngine(settings)
browser_engine = BrowserAutomationEngine(settings)
email_service = EmailNotificationService(db=db, settings=settings)


# ============================================================================
# SIDEBAR NAVIGATION
# ============================================================================

PAGES = [
    "A. Overview",
    "B. Resume Manager",
    "C. Job Discovery",
    "D. AI Job Matching",
    "E. Application Preparation",
    "F. Approval Center",
    "G. Application Tracker",
    "H. Settings",
]

with st.sidebar:
    st.title("🤖 AI Internship Agent")
    st.caption("Human-in-the-Loop Internship Discovery, Matching & Browser Automation")

    if "nav_page" not in st.session_state:
        st.session_state["nav_page"] = PAGES[0]

    def _navigate_to(page_name: str, job_id_val: int | None = None) -> None:
        if job_id_val is not None:
            st.session_state["selected_job_id"] = job_id_val
        st.session_state["nav_page"] = page_name

    selected_page = st.radio(
        "Dashboard Navigation",
        PAGES,
        key="nav_page",
    )

    st.divider()
    active_resume = db.get_active_resume()
    if active_resume:
        st.success(f"**Active Resume:** {active_resume.full_name}")
        st.caption(f"Skills detected: {len(active_resume.skills)}")
    else:
        st.warning("No active resume profile. Upload one in Resume Manager.")

    llm_prov = get_llm_provider(settings)
    st.info(f"**AI Engine:** {llm_prov.provider_name}")
    st.caption(f"📁 **Persistent Profile:** `{browser_engine.get_persistent_profile_dir()}`")
    st.caption("👁️ **Browser Mode:** Visible (`headless=False`)" if not settings.browser_headless else "🕶️ **Browser Mode:** Headless")
    st.caption("🔒 Auto-Submit Disabled • Explicit Approval Enforced")

    st.divider()
    if st.button("🛑 EMERGENCY STOP BROWSER", type="primary", use_container_width=True):
        stop_res = BrowserAutomationEngine.emergency_stop_browser()
        st.error(f"🛑 {stop_res['message']}")


# ============================================================================
# PAGE A: OVERVIEW
# ============================================================================
if selected_page == "A. Overview":
    st.header("📊 A. Executive Overview")
    st.markdown(
        '<div class="safety-banner">🛡️ <b>Human-in-the-Loop Protection Active:</b> '
        "All browser form fills pause prior to final submission and wait for your explicit sign-off in the Approval Center.</div>",
        unsafe_allow_html=True,
    )

    metrics = db.get_overview_metrics()

    col1, col2, col3 = st.columns(3)
    col4, col5, col6 = st.columns(3)

    with col1:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Total Jobs Discovered</div>'
            f'<div class="metric-value">{metrics["total_discovered"]}</div></div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Relevant Jobs (≥60% Match)</div>'
            f'<div class="metric-value">{metrics["relevant_jobs"]}</div></div>',
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Applications Prepared</div>'
            f'<div class="metric-value">{metrics["applications_prepared"]}</div></div>',
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Applications Submitted</div>'
            f'<div class="metric-value">{metrics["applications_submitted"]}</div></div>',
            unsafe_allow_html=True,
        )
    with col5:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Interviews</div>'
            f'<div class="metric-value">{metrics["interviews"]}</div></div>',
            unsafe_allow_html=True,
        )
    with col6:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Rejected Applications</div>'
            f'<div class="metric-value">{metrics["rejected_applications"]}</div></div>',
            unsafe_allow_html=True,
        )

    # ------------------------------------------------------------------------
    # DASHBOARD LAUNCHPAD SECTION (FEATURE 2)
    # ------------------------------------------------------------------------
    st.divider()
    st.subheader("🚀 Dashboard Launchpad & System Telemetry")

    pending_count = len(db.get_drafts(status_filter="Pending Approval"))
    email_cfg = email_service.get_configuration_status()
    prof_status = browser_engine.verify_persistent_profile_state()
    last_disc_time = "Not run yet"
    if REPORT_JSON_PATH.exists():
        try:
            rep_data = json.loads(REPORT_JSON_PATH.read_text(encoding="utf-8"))
            last_disc_time = rep_data.get("generated_at", "Verified")
        except Exception:
            last_disc_time = datetime.fromtimestamp(REPORT_JSON_PATH.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

    lp_s1, lp_s2, lp_s3 = st.columns(3)
    with lp_s1:
        st.info(
            f"**🕘 Current Automation Schedule:**\n`CRON_TZ=Asia/Kolkata 0 9 * * *` (Daily 9:00 AM IST)\n\n"
            f"**📅 Last Successful Discovery Run:**\n`{last_disc_time}`"
        )
    with lp_s2:
        st.warning(
            f"**⏳ Pending Applications (Approval Center):** `{pending_count}`\n\n"
            f"**✅ Total Submitted Applications:** `{metrics['applications_submitted']}`"
        )
    with lp_s3:
        st.success(
            f"**📧 Email Notification Status:**\n`{email_cfg['status_label']}` (`{email_cfg['recipient_email']}`)\n\n"
            f"**🌐 Browser Profile Status:**\n`{'Visible Mode Ready' if prof_status['visible_mode'] else 'Headless'}` (`{prof_status['retained_file_count']} profile files`)"
        )

    st.markdown("**⚡ Quick Navigation Shortcuts:**")
    nav_row1 = st.columns(4)
    nav_row2 = st.columns(4)
    shortcut_buttons = [
        (("📊 Overview", "A. Overview"), nav_row1[0]),
        (("📄 Resume Manager", "B. Resume Manager"), nav_row1[1]),
        (("🔎 Job Discovery", "C. Job Discovery"), nav_row1[2]),
        (("🧠 AI Job Matching", "D. AI Job Matching"), nav_row1[3]),
        (("🛠️ Application Prep", "E. Application Preparation"), nav_row2[0]),
        (("✅ Approval Center", "F. Approval Center"), nav_row2[1]),
        (("📈 Application Tracker", "G. Application Tracker"), nav_row2[2]),
        (("⚙️ Settings", "H. Settings"), nav_row2[3]),
    ]

    for (btn_label, target_p), col_obj in shortcut_buttons:
        with col_obj:
            st.button(
                btn_label,
                key=f"launchpad_btn_{target_p}",
                on_click=_navigate_to,
                args=(target_p,),
                use_container_width=True,
            )

    st.subheader("🚀 Top Ranked Internship Matches")
    ranked = db.get_ranked_matches(active_resume.id if active_resume else None)
    if ranked:
        overview_df = pd.DataFrame(
            [
                {
                    "Rank": idx + 1,
                    "Role": r["title"],
                    "Company": r["company"],
                    "Platform": r["platform"],
                    "Source Status": "✅ Verified Source" if r.get("is_verified_source") else "⚠️ Unverified / Demo Sandbox",
                    "Location": r["location"],
                    "Stipend": r["stipend"],
                    "Compatibility (%)": r["overall_score"],
                    "Recommendation": r["recommendation"],
                }
                for idx, r in enumerate(ranked[:8])
            ]
        )
        st.dataframe(overview_df, use_container_width=True, hide_index=True)
    else:
        st.info("Run AI Job Matching on Page D to view ranked internship opportunities.")

    st.divider()
    st.subheader("🕘 Daily Scheduled Discovery Automation (9:00 AM IST)")
    dcol1, dcol2 = st.columns([1, 2])
    with dcol1:
        st.caption("Schedule: `CRON_TZ=Asia/Kolkata 0 9 * * *` (Every day at 9:00 AM IST)")
        if st.button("▶️ Run Daily 9:00 AM IST Discovery Pipeline Now", type="primary"):
            with st.spinner("Running daily discovery, deduplication, matching, draft prep & report generation..."):
                res_pipe = run_daily_discovery_pipeline(top_k=20, prepare_top_n_drafts=5)
                if res_pipe.get("success"):
                    st.success(
                        f"Daily pipeline complete! Ranked top {res_pipe['summary']['top_ranked_count']} opportunities "
                        f"and prepared {res_pipe['summary']['applications_prepared_for_approval']} drafts (0 auto-submitted)."
                    )
                    st.rerun()
    with dcol2:
        if REPORT_MD_PATH.exists():
            with st.expander("📄 View Latest Daily Discovery Report (`outputs/daily_discovery_report.md`)", expanded=False):
                st.markdown(REPORT_MD_PATH.read_text(encoding="utf-8"))
        else:
            st.info("No daily discovery report generated yet. Click the button on the left to run it now.")

    col_left, col_right = st.columns(2)
    with col_left:
        st.subheader("🎯 Target Roles Configured")
        for r in settings.preferred_roles:
            st.markdown(f"- **{r}**")

    with col_right:
        st.subheader("🌐 Supported Discovery Platforms")
        for p in settings.enabled_platforms:
            st.markdown(f"- **{p}**")


# ============================================================================
# PAGE B: RESUME MANAGER
# ============================================================================
elif selected_page == "B. Resume Manager":
    st.header("📄 B. Resume Manager")
    st.write(
        "Upload your PDF or DOCX resume to extract education, skills, projects, and experience. "
        "Review and edit the extracted profile before saving."
    )

    col_up, col_sample = st.columns([2, 1])
    with col_up:
        uploaded_file = st.file_uploader(
            "Upload Resume (PDF or DOCX)",
            type=["pdf", "docx"],
            help="Supported formats: .pdf (via PyMuPDF) and .docx (via python-docx)",
        )
        if uploaded_file is not None:
            RESUMES_DIR.mkdir(parents=True, exist_ok=True)
            saved_path = RESUMES_DIR / uploaded_file.name
            saved_path.write_bytes(uploaded_file.getbuffer())
            if st.button("🔍 Parse Uploaded Resume", type="primary"):
                try:
                    parsed_profile = ResumeParser.parse_file(
                        saved_path, profile_name=f"{uploaded_file.name} Profile"
                    )
                    st.session_state["editing_resume"] = parsed_profile
                    st.success(f"Extracted structured profile from `{uploaded_file.name}`!")
                except Exception as exc:
                    st.error(f"Failed to parse resume: {exc}")

    with col_sample:
        st.markdown("**Quick Test Resumes**")
        sample_pdf = RESUMES_DIR / "sample_ai_engineer_resume.pdf"
        sample_docx = RESUMES_DIR / "sample_ai_engineer_resume.docx"
        if st.button("📂 Load Sample PDF Resume"):
            st.session_state["editing_resume"] = ResumeParser.parse_file(
                sample_pdf, profile_name="Sample PDF Resume"
            )
            st.success("Loaded and parsed `resumes/sample_ai_engineer_resume.pdf`.")
        if st.button("📂 Load Sample DOCX Resume"):
            st.session_state["editing_resume"] = ResumeParser.parse_file(
                sample_docx, profile_name="Sample DOCX Resume"
            )
            st.success("Loaded and parsed `resumes/sample_ai_engineer_resume.docx`.")

    st.divider()

    current_profile: ResumeProfile = (
        st.session_state.get("editing_resume")
        or db.get_active_resume()
        or ResumeProfile(profile_name="New Resume Profile")
    )

    st.subheader("✏️ Review & Edit Extracted Resume Profile")
    with st.form("resume_profile_editor_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            profile_name = st.text_input("Profile Label", value=current_profile.profile_name)
            full_name = st.text_input("Full Name *", value=current_profile.full_name)
            email = st.text_input("Email *", value=current_profile.email)
        with c2:
            phone = st.text_input("Phone *", value=current_profile.phone)
            location = st.text_input("Location", value=current_profile.location)
            file_path_str = st.text_input("Resume File Path", value=current_profile.file_path)
        with c3:
            linkedin_url = st.text_input("LinkedIn URL", value=current_profile.linkedin_url)
            github_url = st.text_input("GitHub URL", value=current_profile.github_url)
            portfolio_url = st.text_input("Portfolio URL", value=current_profile.portfolio_url)

        summary = st.text_area("Professional Summary", value=current_profile.summary, height=80)

        skills_csv = st.text_area(
            "Extracted Skills (comma-separated)",
            value=", ".join(current_profile.skills),
            height=70,
        )

        st.markdown("**Education (JSON list of `{degree, institution, year, gpa}`)**")
        edu_json_str = st.text_area(
            "Education Entries",
            value=json.dumps([e.model_dump() for e in current_profile.education], indent=2),
            height=130,
        )

        st.markdown("**Projects (JSON list of `{name, description, technologies}`)**")
        proj_json_str = st.text_area(
            "Project Entries",
            value=json.dumps([p.model_dump() for p in current_profile.projects], indent=2),
            height=160,
        )

        st.markdown("**Experience (JSON list of `{role, company, duration, summary}`)**")
        exp_json_str = st.text_area(
            "Experience Entries",
            value=json.dumps([x.model_dump() for x in current_profile.experience], indent=2),
            height=150,
        )

        raw_text_val = st.text_area("Raw Resume Text", value=current_profile.raw_text, height=120)

        save_btn = st.form_submit_button("💾 Save Approved Resume Profile", type="primary")
        if save_btn:
            try:
                edu_list = [EducationItem(**item) for item in json.loads(edu_json_str or "[]")]
                proj_list = [ProjectItem(**item) for item in json.loads(proj_json_str or "[]")]
                exp_list = [ExperienceItem(**item) for item in json.loads(exp_json_str or "[]")]
                skill_list = [s.strip() for s in skills_csv.split(",") if s.strip()]

                updated_profile = ResumeProfile(
                    id=current_profile.id,
                    profile_name=profile_name,
                    full_name=full_name,
                    email=email,
                    phone=phone,
                    location=location,
                    linkedin_url=linkedin_url,
                    github_url=github_url,
                    portfolio_url=portfolio_url,
                    summary=summary,
                    education=edu_list,
                    skills=skill_list,
                    projects=proj_list,
                    experience=exp_list,
                    raw_text=raw_text_val,
                    file_path=file_path_str,
                    is_active=True,
                )
                saved_id = db.save_resume_profile(updated_profile)
                updated_profile.id = saved_id
                st.session_state["editing_resume"] = updated_profile
                st.success(f"Approved Resume Profile saved (ID={saved_id}) and set as active!")
            except Exception as exc:
                st.error(f"Error saving resume profile: {exc}")


# ============================================================================
# PAGE C: JOB DISCOVERY
# ============================================================================
elif selected_page == "C. Job Discovery":
    st.header("🔎 C. Job Discovery")
    st.write(
        "Discover internships across LinkedIn, Internshala, Wellfound, Naukri, Indeed, and Official Career Pages "
        "using legitimate public feeds and authorized discovery methods."
    )

    fcol1, fcol2, fcol3, fcol4 = st.columns([2, 2, 2, 1])
    with fcol1:
        role_filter = st.selectbox("Target Role", ["All"] + TARGET_ROLES_DEFAULT)
    with fcol2:
        loc_filter = st.selectbox(
            "Location",
            ["All", "Remote", "Bangalore", "Hyderabad", "Pune", "Delhi NCR", "Mumbai", "Chennai", "India"],
        )
    with fcol3:
        plat_filter = st.selectbox("Platform", ["All"] + TARGET_PLATFORMS_DEFAULT)
    with fcol4:
        live_api_toggle = st.checkbox("Include Public API/RSS", value=False)

    bcol1, bcol2 = st.columns([1, 3])
    with bcol1:
        if st.button("🚀 Run Discovery Scan", type="primary"):
            discovery_engine = JobDiscoveryEngine(daily_limit=settings.daily_discovery_limit)
            found = discovery_engine.discover_opportunities(
                role=role_filter,
                location=loc_filter,
                platform=plat_filter,
                include_live_api=live_api_toggle,
            )
            new_count = 0
            for j in found:
                _, is_new = db.upsert_job_listing(j)
                if is_new:
                    new_count += 1
            st.success(f"Discovery complete! Found {len(found)} matching listings ({new_count} newly added).")

    with st.expander("➕ Add Custom Public Internship Listing or Official Career Page URL"):
        with st.form("add_custom_job_form"):
            cj1, cj2, cj3 = st.columns(3)
            with cj1:
                c_title = st.text_input("Job Title *", placeholder="Agentic AI Intern")
                c_company = st.text_input("Company *", placeholder="DeepMind / OpenAI / Startup")
            with cj2:
                c_role = st.selectbox("Role Category", TARGET_ROLES_DEFAULT)
                c_plat = st.selectbox("Platform", TARGET_PLATFORMS_DEFAULT)
            with cj3:
                c_loc = st.text_input("Location", value="Remote")
                c_stipend = st.text_input("Stipend", value="₹45,000 / month")
            c_url = st.text_input(
                "Application URL *",
                value=(Path("data/mock_portals/portal_agentic_ai.html").resolve().as_uri()),
            )
            c_desc = st.text_area(
                "Job Description *",
                placeholder="Paste the full internship description here...",
            )
            if st.form_submit_button("💾 Save Opportunity"):
                if c_title and c_company and c_url:
                    extracted_sk = extract_skills_from_text(c_title + " " + c_desc)
                    new_job = JobListing(
                        title=c_title,
                        company=c_company,
                        location=c_loc,
                        stipend=c_stipend,
                        platform=c_plat,
                        role_category=c_role,
                        application_url=c_url,
                        description=c_desc,
                        required_skills=extracted_sk,
                        is_saved=True,
                    )
                    jid, _ = db.upsert_job_listing(new_job)
                    st.success(f"Saved internship opportunity '{c_title}' at {c_company} (ID={jid})!")
                else:
                    st.warning("Please fill in Title, Company, and Application URL.")

    with st.expander("🔗 Direct Authorized Public Search Links (LinkedIn, Internshala, Wellfound, Naukri, Indeed)"):
        search_role = role_filter if role_filter != "All" else "AI Engineer"
        search_loc = loc_filter if loc_filter != "All" else "India"
        links = JobDiscoveryEngine.build_authorized_search_links(search_role, search_loc)
        lcols = st.columns(len(links))
        for idx, (pname, purl) in enumerate(links.items()):
            lcols[idx].markdown(f"[{pname} ↗]({purl})")

    jobs = db.get_job_listings(
        role_filter=role_filter,
        location_filter=loc_filter,
        platform_filter=plat_filter,
    )

    ver_filter = st.radio(
        "Source Verification Filter",
        ["All Listings", "✅ Verified Source URLs Only", "⚠️ Unverified / Demo Sandbox Listings Only"],
        horizontal=True,
    )
    if ver_filter == "✅ Verified Source URLs Only":
        jobs = [j for j in jobs if j.is_verified_source]
    elif ver_filter == "⚠️ Unverified / Demo Sandbox Listings Only":
        jobs = [j for j in jobs if not j.is_verified_source]

    st.subheader(f"📋 Discovered Internship Listings ({len(jobs)})")
    for job in jobs:
        with st.container(border=True):
            jc1, jc2, jc3 = st.columns([4, 2, 2])
            with jc1:
                badge = (
                    f"✅ **VERIFIED SOURCE** (`{job.verification_status}`)"
                    if job.is_verified_source
                    else f"⚠️ **UNVERIFIED LISTING** (`{job.verification_status}`)"
                )
                st.markdown(f"### {job.title}")
                st.markdown(badge)
                st.markdown(f"**{job.company}** • 📍 {job.location} • 💰 **{job.stipend}**")
                st.caption(f"Platform: `{job.platform}` | Role Category: `{job.role_category}` | Posted: {job.posted_date}")
                if job.required_skills:
                    st.markdown("**Required Skills:** " + ", ".join(f"`{s}`" for s in job.required_skills))
            with jc2:
                st.markdown(f"**Application URL:**\n[{job.application_url[:42]}...]({job.application_url})")
                st.caption(f"Source URL: `{job.source_url[:45]}`")
                already_done = db.has_already_applied(job.id, job.company, job.title, job.application_url)
                if already_done:
                    st.success("✔ Already Applied")
            with jc3:
                save_label = "⭐ Saved Opportunity" if job.is_saved else "☆ Save Opportunity"
                if st.button(save_label, key=f"save_job_{job.id}"):
                    db.set_job_saved(job.id, not job.is_saved)
                    st.rerun()
                st.button(
                    "🛠️ Prepare Application",
                    key=f"prep_from_disc_{job.id}",
                    on_click=_navigate_to,
                    args=("E. Application Preparation", job.id),
                )
            with st.expander("View Full Job Description"):
                st.write(job.description)


# ============================================================================
# PAGE D: AI JOB MATCHING
# ============================================================================
elif selected_page == "D. AI Job Matching":
    st.header("🧠 D. AI Job Matching & Compatibility Engine")
    st.write(
        "Analyze job descriptions against your active resume profile, compute multi-factor compatibility scores, "
        "explain missing skills, and rank opportunities."
    )

    if not active_resume:
        st.error("Please upload or save an active resume profile on Page B first.")
    else:
        all_jobs = db.get_job_listings()
        mcol1, mcol2 = st.columns([1, 2])
        with mcol1:
            if st.button("⚡ Evaluate & Rank All Discovered Jobs", type="primary"):
                for j in all_jobs:
                    m = ai_engine.evaluate_job_compatibility(active_resume, j)
                    db.save_job_match(m)
                st.success(f"Evaluated {len(all_jobs)} jobs against '{active_resume.full_name}'!")

        ranked_matches = db.get_ranked_matches(active_resume.id)
        if ranked_matches:
            st.subheader("🏆 Ranked Opportunities")
            rank_df = pd.DataFrame(
                [
                    {
                        "Rank": i + 1,
                        "Job ID": m["job_id"],
                        "Role": m["title"],
                        "Company": m["company"],
                        "Platform": m["platform"],
                        "Source Verification": (
                            f"✅ Verified ({m.get('verification_status', '')})"
                            if m.get("is_verified_source")
                            else f"⚠️ Unverified ({m.get('verification_status', '')})"
                        ),
                        "Overall Match (%)": m["overall_score"],
                        "Skill Score (%)": m["skill_score"],
                        "Semantic Score (%)": m["semantic_score"],
                        "Role Alignment (%)": m["role_alignment_score"],
                        "Missing Skills": ", ".join(m["missing_skills"]) or "None (100% Match)",
                        "Recommendation": m["recommendation"],
                    }
                    for i, m in enumerate(ranked_matches)
                ]
            )
            st.dataframe(rank_df, use_container_width=True, hide_index=True)

            st.subheader("🔍 Detailed Compatibility & Missing Skills Breakdown")
            for m in ranked_matches:
                with st.expander(
                    f"#{m['job_id']} | {m['title']} at {m['company']} — {m['overall_score']}% ({m['recommendation']})"
                ):
                    sc1, sc2, sc3, sc4 = st.columns(4)
                    sc1.metric("Overall Compatibility", f"{m['overall_score']}%")
                    sc2.metric("Skill Coverage", f"{m['skill_score']}%")
                    sc3.metric("Semantic Similarity", f"{m['semantic_score']}%")
                    sc4.metric("Role Alignment", f"{m['role_alignment_score']}%")

                    st.markdown(f"**AI Analysis:** {m['explanation']}")
                    st.markdown(
                        "**✅ Matched Skills:** "
                        + (", ".join(f"`{s}`" for s in m["matched_skills"]) if m["matched_skills"] else "None")
                    )
                    st.markdown(
                        "**⚠️ Missing Skills to Address:** "
                        + (
                            ", ".join(f"`{s}`" for s in m["missing_skills"])
                            if m["missing_skills"]
                            else "🎉 Zero missing skills!"
                        )
                    )
                    st.button(
                        f"✍️ Prepare Application for {m['company']}",
                        key=f"prep_from_match_{m['job_id']}",
                        on_click=_navigate_to,
                        args=("E. Application Preparation", m["job_id"]),
                    )


# ============================================================================
# PAGE E: APPLICATION PREPARATION
# ============================================================================
elif selected_page == "E. Application Preparation":
    st.header("🛠️ E. Application Preparation & Playwright Form Filler")
    st.markdown(
        '<div class="safety-banner">🔐 <b>Privacy & Credential Security Guarantee:</b> '
        "The browser runs in <b>Visible Mode</b> using your private local persistent profile "
        f"(<code>{browser_engine.get_persistent_profile_dir()}</code>). "
        "Sign in manually inside the visible browser window when needed. "
        "<b>Never provide passwords, OTPs, or session cookies to the AI.</b></div>",
        unsafe_allow_html=True,
    )

    ctrl_c1, ctrl_c2 = st.columns([2, 1])
    with ctrl_c2:
        if st.button("🛑 EMERGENCY STOP BROWSER", key="emergency_stop_page_e", use_container_width=True):
            stop_res = BrowserAutomationEngine.emergency_stop_browser()
            st.error(f"🛑 {stop_res['message']}")

    with st.expander("🔑 Manual Sign-In Workflow & Local Session Retention Verifier (Internshala, Wellfound, Naukri & Career Portals)"):
        prof_state = browser_engine.verify_persistent_profile_state()
        st.markdown(
            f"- **Persistent Profile Path:** `{prof_state['profile_dir']}`\n"
            f"- **Profile Directory Writable:** `{prof_state['is_writable']}` | **Visible Mode (`headless=False`):** `{prof_state['visible_mode']}`\n"
            f"- **Retained Profile Files:** `{prof_state['retained_file_count']}` | **Session Artifacts:** `{', '.join(prof_state['session_artifacts_present'])}`\n"
            f"- **Authenticated Portals Recorded:** `{', '.join(prof_state['authenticated_portals_recorded']) or 'None recorded yet'}`"
        )
        ms_c1, ms_c2, ms_c3 = st.columns([2, 1, 1])
        with ms_c1:
            portal_choice = st.selectbox(
                "Select Platform or Career Portal for Manual Sign-In",
                list(browser_engine.SUPPORTED_PORTAL_LOGIN_URLS.keys()),
            )
        with ms_c2:
            if st.button("🌐 Open Visible Login Window", use_container_width=True):
                target_login_url = browser_engine.SUPPORTED_PORTAL_LOGIN_URLS[portal_choice]
                res_login = browser_engine.launch_manual_login_session(
                    login_url=target_login_url,
                    platform_name=portal_choice,
                    wait_for_user_close=False,
                )
                if res_login["success"]:
                    st.success(res_login["message"])
                else:
                    st.info(res_login["message"])
        with ms_c3:
            if st.button("🔄 Verify Session Retention", use_container_width=True):
                updated_state = browser_engine.verify_persistent_profile_state()
                st.success(
                    f"Verified persistent profile ({updated_state['retained_file_count']} files retained at {updated_state['last_verified_at']})!"
                )
        st.caption(
            "💡 **Windows Desktop CLI Command for Interactive Sign-In (keeps browser open until you close it):** "
            f"`python -m src.browser_automation --login \"{portal_choice}\"`"
        )

    all_jobs = db.get_job_listings()
    all_resumes = db.get_all_resumes()

    if not all_jobs or not all_resumes:
        st.warning("Ensure you have at least one saved resume profile and one discovered job listing.")
    else:
        job_options = {j.id: f"#{j.id} - {j.title} at {j.company} ({j.platform})" for j in all_jobs}
        default_jid = st.session_state.get("selected_job_id", all_jobs[0].id)
        if default_jid not in job_options:
            default_jid = all_jobs[0].id

        pcol1, pcol2 = st.columns(2)
        with pcol1:
            selected_jid = st.selectbox(
                "Select Target Internship",
                options=list(job_options.keys()),
                format_func=lambda x: job_options[x],
                index=list(job_options.keys()).index(default_jid),
            )
        with pcol2:
            resume_options = {r.id: f"#{r.id} - {r.profile_name} ({r.full_name})" for r in all_resumes}
            selected_rid = st.selectbox(
                "Select Approved Resume Profile",
                options=list(resume_options.keys()),
                format_func=lambda x: resume_options[x],
            )

        target_job = db.get_job_by_id(selected_jid)
        target_resume = next((r for r in all_resumes if r.id == selected_rid), active_resume)

        if target_job and target_resume:
            if db.has_already_applied(
                target_job.id, target_job.company, target_job.title, target_job.application_url
            ):
                st.error(
                    f"⚠️ Duplicate Application Protection: You have already applied to **{target_job.title}** at **{target_job.company}**."
                )

            # Platform Terms Compliance Check Banner (Requirements 7 & 8)
            terms_status = browser_engine.check_platform_terms_compliance(
                target_job.application_url, target_job.platform
            )
            if terms_status["automation_permitted"]:
                st.success(
                    f"✅ **Terms Compliance Verified ({terms_status['policy_status']}):** {terms_status['reason']}"
                )
            else:
                st.warning(
                    f"⚠️ **Browser Automation Disabled for {target_job.platform} ({terms_status['policy_status']}):** "
                    f"{terms_status['reason']}"
                )

            existing_draft = db.get_draft_by_job_id(target_job.id)

            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("✨ Generate Customized Cover Letter & Form Answers", type="primary"):
                    match_eval = ai_engine.evaluate_job_compatibility(target_resume, target_job)
                    db.save_job_match(match_eval)
                    cover_letter = ai_engine.generate_cover_letter(target_resume, target_job, match_eval)
                    form_answers = ai_engine.prepare_form_answers(target_resume, target_job, cover_letter)
                    st.session_state[f"draft_cl_{target_job.id}"] = cover_letter
                    st.session_state[f"draft_fa_{target_job.id}"] = form_answers
                    st.success("Generated fact-grounded cover letter and form payload!")
            with btn_col2:
                if st.button("🔑 Launch Visible Browser for Manual Sign-In (Persistent Profile)"):
                    login_res = browser_engine.launch_manual_login_session(
                        target_job.application_url, target_job.platform
                    )
                    if login_res["success"]:
                        st.info(login_res["message"])
                    else:
                        st.warning(login_res["message"])

            default_cl = (
                st.session_state.get(f"draft_cl_{target_job.id}")
                or (existing_draft["cover_letter"] if existing_draft else "")
                or ai_engine.generate_cover_letter(target_resume, target_job)
            )
            default_fa = (
                st.session_state.get(f"draft_fa_{target_job.id}")
                or (existing_draft["form_payload"] if existing_draft else {})
                or ai_engine.prepare_form_answers(target_resume, target_job, default_cl)
            )

            with st.form("prepare_application_form"):
                st.subheader("1. Resume File Attachment")
                available_files = [str(p) for p in RESUMES_DIR.glob("*") if p.suffix.lower() in (".pdf", ".docx")]
                default_file = (
                    existing_draft["resume_file_path"]
                    if existing_draft and existing_draft.get("resume_file_path")
                    else (target_resume.file_path or (available_files[0] if available_files else ""))
                )
                selected_resume_file = st.text_input(
                    "Resume File Path to Upload",
                    value=default_file,
                )

                st.subheader("2. Customized Cover Letter (Grounded Strictly in Resume)")
                edited_cl = st.text_area("Cover Letter", value=default_cl, height=220)

                st.subheader("3. Application Form Field Answers")
                fc1, fc2 = st.columns(2)
                with fc1:
                    f_name = st.text_input("Full Name", value=default_fa.get("full_name", target_resume.full_name))
                    f_email = st.text_input("Email", value=default_fa.get("email", target_resume.email))
                    f_phone = st.text_input("Phone", value=default_fa.get("phone", target_resume.phone))
                    f_loc = st.text_input(
                        "Current Location", value=default_fa.get("current_location", target_resume.location)
                    )
                    f_linkedin = st.text_input(
                        "LinkedIn URL", value=default_fa.get("linkedin_url", target_resume.linkedin_url)
                    )
                with fc2:
                    f_github = st.text_input(
                        "GitHub URL", value=default_fa.get("github_url", target_resume.github_url)
                    )
                    f_degree = st.text_input("Degree", value=default_fa.get("degree", ""))
                    f_inst = st.text_input("Institution", value=default_fa.get("institution", ""))
                    f_gpa = st.text_input("CGPA / GPA", value=default_fa.get("gpa", ""))
                    f_avail = st.text_input(
                        "Availability", value=default_fa.get("availability", "Immediate / Full-time Internship")
                    )

                f_skills = st.text_input("Primary Verified Skills", value=default_fa.get("primary_skills", ""))
                f_why = st.text_area("Why This Role / Company?", value=default_fa.get("why_this_role", ""), height=90)

                b_save, b_autofill = st.columns(2)
                with b_save:
                    save_only_clicked = st.form_submit_button("💾 Save Prepared Application Draft")
                with b_autofill:
                    autofill_clicked = st.form_submit_button(
                        "🤖 Run Playwright Form Pre-Fill (Stops Before Final Submit)",
                        type="primary",
                    )

                if save_only_clicked or autofill_clicked:
                    BrowserAutomationEngine.reset_emergency_stop()
                    payload = {
                        "full_name": f_name,
                        "email": f_email,
                        "phone": f_phone,
                        "current_location": f_loc,
                        "linkedin_url": f_linkedin,
                        "github_url": f_github,
                        "degree": f_degree,
                        "institution": f_inst,
                        "gpa": f_gpa,
                        "availability": f_avail,
                        "primary_skills": f_skills,
                        "why_this_role": f_why,
                        "cover_letter": edited_cl,
                    }

                    auto_status = "Draft Saved (Awaiting Browser Fill or Approval)"
                    shot_path = existing_draft["screenshot_path"] if existing_draft else ""
                    det_fields = existing_draft["detected_fields"] if existing_draft else []

                    if autofill_clicked:
                        with st.spinner("Checking Terms compliance, launching visible persistent browser, filling form & stopping before Submit..."):
                            auto_res = browser_engine.inspect_and_fill_application(
                                url=target_job.application_url,
                                form_payload=payload,
                                resume_file_path=selected_resume_file,
                                submit_after_fill=False,
                                explicit_human_approval=False,
                                company=target_job.company,
                                role=target_job.title,
                                platform=target_job.platform,
                            )
                            auto_status = auto_res["status"]
                            shot_path = auto_res["screenshot_path"]
                            det_fields = auto_res["detected_fields"]
                            if auto_res.get("manual_package"):
                                st.session_state[f"manual_pkg_{target_job.id}"] = auto_res["manual_package"]
                            if auto_res["success"]:
                                st.success(auto_res["message"])
                            else:
                                st.warning(auto_res["message"])

                    try:
                        draft_obj = ApplicationDraft(
                            job_id=target_job.id,
                            resume_id=target_resume.id,
                            cover_letter=edited_cl,
                            form_Payload=payload,
                            resume_file_path=selected_resume_file,
                            automation_status=auto_status,
                            screenshot_path=shot_path,
                            detected_fields=det_fields,
                            status="Pending Approval",
                        )
                        draft_id = db.save_application_draft(draft_obj)
                        email_service.send_awaiting_approval_notification(
                            draft_id=draft_id,
                            company=target_job.company,
                            role=target_job.title,
                            platform=target_job.platform,
                            application_url=target_job.application_url,
                        )
                        st.info(
                            f"Prepared Application Draft ID=#{draft_id} saved and queued in **F. Approval Center**!"
                        )
                    except Exception as exc:
                        st.error(str(exc))

            # Requirement 14: Display Direct Application URL and Prepared Application Package whenever manual completion is needed
            manual_pkg = st.session_state.get(f"manual_pkg_{target_job.id}")
            if not terms_status["automation_permitted"] and not manual_pkg:
                manual_pkg = browser_engine.build_manual_application_package(
                    url=target_job.application_url,
                    company=target_job.company,
                    role=target_job.title,
                    platform=target_job.platform,
                    form_payload=default_fa,
                    cover_letter=default_cl,
                    resume_file_path=default_file,
                    reason=terms_status["reason"],
                )

            if manual_pkg:
                st.subheader("📦 Prepared Application Package for Manual Completion")
                st.info(
                    f"**Direct Application URL:** [{manual_pkg['direct_application_url']}]({manual_pkg['direct_application_url']})\n\n"
                    f"**Reason for Manual Completion:** {manual_pkg['reason']}\n\n"
                    f"**Resume File to Attach:** `{manual_pkg['resume_file_path']}`"
                )
                pk_c1, pk_c2 = st.columns(2)
                if Path(manual_pkg["package_md_path"]).exists():
                    pk_c1.download_button(
                        "📥 Download Prepared Application Package (.md)",
                        data=Path(manual_pkg["package_md_path"]).read_bytes(),
                        file_name=Path(manual_pkg["package_md_path"]).name,
                        mime="text/markdown",
                        use_container_width=True,
                    )
                if Path(manual_pkg["package_json_path"]).exists():
                    pk_c2.download_button(
                        "📥 Download Prepared Application Package (.json)",
                        data=Path(manual_pkg["package_json_path"]).read_bytes(),
                        file_name=Path(manual_pkg["package_json_path"]).name,
                        mime="application/json",
                        use_container_width=True,
                    )

            latest_draft = db.get_draft_by_job_id(target_job.id)
            if latest_draft and latest_draft.get("screenshot_path") and Path(latest_draft["screenshot_path"]).exists():
                st.subheader("📸 Playwright Pre-Submission Screenshot Proof (Stopped Before Final Submit)")
                st.image(
                    latest_draft["screenshot_path"],
                    caption=f"Pre-filled application form for {target_job.title} at {target_job.company} (Stopped before Submit — awaiting Approval Center sign-off)",
                    use_container_width=True,
                )


# ============================================================================
# PAGE F: APPROVAL CENTER
# ============================================================================
elif selected_page == "F. Approval Center":
    st.header("✅ F. Human-in-the-Loop Approval Center")
    st.markdown(
        '<div class="safety-banner">🔒 <b>Two-Mode Human Approval Gate:</b><br>'
        "• <b>1. APPROVE AND SUBMIT:</b> For platforms where automated submission is permitted — submits the form only after your explicit confirmation dialog approval.<br>"
        "• <b>2. MARK AS MANUALLY SUBMITTED:</b> For LinkedIn, Indeed, and other restricted platforms where you submit the application yourself — updates only the SQLite application status, submission date, and audit log without ever opening or submitting the browser form again.</div>",
        unsafe_allow_html=True,
    )

    if st.button("🛑 EMERGENCY STOP BROWSER", key="emergency_stop_page_f"):
        stop_res = BrowserAutomationEngine.emergency_stop_browser()
        st.error(f"🛑 {stop_res['message']}")

    @st.dialog("Confirm Automated Submission (Approve and Submit)")
    def confirm_approve_and_submit_dialog(draft_item: Dict[str, Any], notes_val: str) -> None:
        st.markdown(f"### ✅ Approve and Submit: **{draft_item['title']}** at **{draft_item['company']}**")
        st.write(
            "You are authorizing the agent to perform final submission on this permitted portal and record the application in SQLite."
        )
        st.markdown(
            f"- **Platform:** `{draft_item['platform']}`\n"
            f"- **Application URL:** `{draft_item['application_url']}`\n"
            f"- **Uploaded Resume:** `{draft_item.get('resume_file_path', 'None')}`"
        )
        dialog_confirm = st.checkbox(
            f"I explicitly confirm all form values and resume attachment for {draft_item['title']} at {draft_item['company']} and authorize final submission.",
            value=False,
            key=f"dlg_chk_auto_{draft_item['id']}",
        )
        dc1, dc2 = st.columns(2)
        with dc1:
            if st.button("🚀 Confirm & Execute Submission", type="primary", use_container_width=True):
                if not dialog_confirm:
                    st.error("Please check the explicit confirmation box above to proceed.")
                else:
                    BrowserAutomationEngine.reset_emergency_stop()
                    final_shot = draft_item.get("screenshot_path", "")
                    res = browser_engine.inspect_and_fill_application(
                        url=draft_item["application_url"],
                        form_payload=draft_item["form_payload"],
                        resume_file_path=draft_item["resume_file_path"],
                        submit_after_fill=True,
                        explicit_human_approval=True,
                        company=draft_item["company"],
                        role=draft_item["title"],
                        platform=draft_item["platform"],
                    )
                    if res.get("screenshot_path"):
                        final_shot = res["screenshot_path"]
                    portal_confirmed_flag = bool(res.get("submitted"))
                    if not res.get("success") and not portal_confirmed_flag:
                        email_service.send_submission_failure_notification(
                            company=draft_item["company"],
                            role=draft_item["title"],
                            platform=draft_item["platform"],
                            application_url=draft_item["application_url"],
                            error_reason=res.get("message", "Submission could not be verified on portal"),
                            draft_id=draft_item["id"],
                        )
                    try:
                        app_id = db.approve_and_record_submission(
                            draft_id=draft_item["id"],
                            reviewer_notes=notes_val,
                            confirmed_checkbox=True,
                            final_screenshot_path=final_shot,
                            portal_confirmed=portal_confirmed_flag,
                        )
                        st.session_state.pop(f"inline_action_{draft_item['id']}", None)
                        st.success(f"Approved and submitted! Recorded in SQLite Application Tracker (ID=#{app_id}).")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
        with dc2:
            if st.button("Cancel", key=f"dlg_cancel_auto_{draft_item['id']}", use_container_width=True):
                st.session_state.pop(f"inline_action_{draft_item['id']}", None)
                st.rerun()

    @st.dialog("Confirm Manual Submission Record (No Browser Re-Open)")
    def confirm_manual_submission_dialog(draft_item: Dict[str, Any], notes_val: str) -> None:
        st.markdown(f"### 📝 Mark as Manually Submitted: **{draft_item['title']}** at **{draft_item['company']}**")
        st.info(
            "🔒 **No-Browser Guarantee:** This action will **never** open Playwright or submit any form. "
            "It only updates the SQLite application status, records your submission date, prevents duplicates, and writes an audit log entry."
        )
        st.markdown(
            f"- **Platform:** `{draft_item['platform']}`\n"
            f"- **Direct URL Used:** `{draft_item['application_url']}`\n"
            f"- **Resume Used:** `{draft_item.get('resume_file_path', 'None')}`"
        )
        manual_date_str = st.text_input(
            "Submission Date (YYYY-MM-DD)",
            value=datetime.now().strftime("%Y-%m-%d"),
            key=f"dlg_manual_date_{draft_item['id']}",
        )
        dialog_confirm = st.checkbox(
            f"I confirm that I have submitted the application for {draft_item['title']} at {draft_item['company']} myself and want to record it in SQLite.",
            value=False,
            key=f"dlg_chk_manual_{draft_item['id']}",
        )
        mc1, mc2 = st.columns(2)
        with mc1:
            if st.button("💾 Confirm & Record in SQLite Only", type="primary", use_container_width=True):
                if not dialog_confirm:
                    st.error("Please check the explicit confirmation box above to proceed.")
                else:
                    try:
                        app_id = db.mark_as_manually_submitted(
                            draft_id=draft_item["id"],
                            reviewer_notes=notes_val,
                            confirmed_checkbox=True,
                            submission_date=manual_date_str,
                        )
                        st.session_state.pop(f"inline_action_{draft_item['id']}", None)
                        st.success(
                            f"Recorded as Manually Submitted in SQLite Application Tracker (ID=#{app_id}) on {manual_date_str}!"
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
        with mc2:
            if st.button("Cancel", key=f"dlg_cancel_manual_{draft_item['id']}", use_container_width=True):
                st.session_state.pop(f"inline_action_{draft_item['id']}", None)
                st.rerun()

    pending_drafts = db.get_drafts(status_filter="Pending Approval")
    if not pending_drafts:
        st.info("No pending application drafts awaiting approval. Prepare an application on Page E first.")
    else:
        st.subheader(f"🕒 Pending Applications Awaiting Your Decision ({len(pending_drafts)})")
        for draft in pending_drafts:
            with st.container(border=True):
                st.markdown(f"### 🏢 {draft['company']} — **{draft['title']}**")
                st.caption(
                    f"Draft ID: `#{draft['id']}` | Platform: `{draft['platform']}` | "
                    f"Location: `{draft['location']}` | Automation Status: `{draft['automation_status']}`"
                )
                st.markdown(f"**Direct Application URL:** [{draft['application_url']}]({draft['application_url']})")

                already_submitted = db.has_already_applied(
                    draft["job_id"], draft["company"], draft["title"], draft["application_url"]
                )
                if already_submitted:
                    st.error("🚫 **Duplicate Prevention Active:** An application for this role is already recorded in SQLite.")

                terms_info = browser_engine.check_platform_terms_compliance(
                    draft["application_url"], draft["platform"]
                )
                automation_permitted = bool(terms_info["automation_permitted"])
                if automation_permitted:
                    st.success(
                        f"✅ **Automated Submission Permitted ({terms_info['policy_status']}):** "
                        "You may use **1. APPROVE AND SUBMIT** (or **2. MARK AS MANUALLY SUBMITTED** if you submitted it yourself)."
                    )
                else:
                    st.warning(
                        f"⚠️ **Restricted Platform ({terms_info['policy_status']}):** {terms_info['reason']} "
                        "Automated submission is disabled — submit manually via the Direct Application URL and click **2. MARK AS MANUALLY SUBMITTED**."
                    )

                r_path = draft.get("resume_file_path", "")
                r_exists = bool(r_path and Path(r_path).exists())
                st.markdown(
                    f"**📎 Uploaded Resume File:** `{r_path or 'None'}` "
                    + ("✅ *(Verified on disk)*" if r_exists else "⚠️ *(File path not found)*")
                )

                col_vals, col_shot = st.columns([3, 2])
                with col_vals:
                    st.markdown("**📋 Complete Form Values Before Submission:**")
                    payload_items = [
                        {"Form Field": k, "Prepared Value": str(v)}
                        for k, v in draft["form_payload"].items()
                        if k != "cover_letter"
                    ]
                    st.dataframe(pd.DataFrame(payload_items), use_container_width=True, hide_index=True)

                    with st.expander("📄 Inspect Customized Cover Letter"):
                        st.text(draft["cover_letter"])

                    pkg = browser_engine.build_manual_application_package(
                        url=draft["application_url"],
                        company=draft["company"],
                        role=draft["title"],
                        platform=draft["platform"],
                        form_payload=draft["form_payload"],
                        cover_letter=draft["cover_letter"],
                        resume_file_path=r_path,
                        reason=terms_info["reason"],
                    )
                    with st.expander("📦 Prepared Application Package (For Manual Completion on Restricted Portals)"):
                        st.markdown(f"**Direct URL:** [{pkg['direct_application_url']}]({pkg['direct_application_url']})")
                        if Path(pkg["package_md_path"]).exists():
                            st.download_button(
                                "📥 Download Prepared Package (.md)",
                                data=Path(pkg["package_md_path"]).read_bytes(),
                                file_name=Path(pkg["package_md_path"]).name,
                                mime="text/markdown",
                                key=f"dl_md_approve_{draft['id']}",
                            )

                with col_shot:
                    if draft.get("screenshot_path") and Path(draft["screenshot_path"]).exists():
                        st.markdown("**📸 Browser Pre-Fill Preview (Stopped Before Submit):**")
                        st.image(draft["screenshot_path"], use_container_width=True)
                    else:
                        st.info("No browser screenshot captured yet. Review all form fields on the left.")

                st.divider()
                reviewer_notes = st.text_input(
                    "Reviewer / Audit Log Notes",
                    value=f"Reviewed all fields and resume for {draft['company']}.",
                    key=f"notes_{draft['id']}",
                )

                ac1, ac2, ac3 = st.columns(3)
                with ac1:
                    if st.button(
                        "✅ 1. APPROVE AND SUBMIT",
                        key=f"btn_approve_{draft['id']}",
                        type="primary",
                        disabled=(not automation_permitted) or already_submitted,
                        help=(
                            "Permitted platform: opens confirmation dialog to submit after explicit approval."
                            if automation_permitted
                            else "Disabled for restricted platforms (LinkedIn, Indeed, unverified terms). Use '2. MARK AS MANUALLY SUBMITTED'."
                        ),
                        use_container_width=True,
                    ):
                        st.session_state[f"inline_action_{draft['id']}"] = "AUTO_SUBMIT"
                        confirm_approve_and_submit_dialog(draft, reviewer_notes)

                with ac2:
                    if st.button(
                        "📝 2. MARK AS MANUALLY SUBMITTED",
                        key=f"btn_manual_submit_{draft['id']}",
                        disabled=already_submitted,
                        help="For LinkedIn, Indeed, and other restricted platforms where you submitted the application yourself. Updates SQLite & audit log only; never opens the browser.",
                        use_container_width=True,
                    ):
                        st.session_state[f"inline_action_{draft['id']}"] = "MANUAL_SUBMIT"
                        confirm_manual_submission_dialog(draft, reviewer_notes)

                with ac3:
                    if st.button(
                        "❌ Reject Application",
                        key=f"btn_reject_{draft['id']}",
                        use_container_width=True,
                    ):
                        db.reject_application_draft(draft_id=draft["id"], reviewer_notes=reviewer_notes)
                        st.warning(f"Application draft for {draft['company']} rejected.")
                        st.rerun()

    st.divider()
    st.subheader("📜 Approval Audit History")
    history = db.get_approval_history()
    if history:
        hist_df = pd.DataFrame(
            [
                {
                    "Audit ID": h["id"],
                    "Draft ID": h["draft_id"],
                    "Company": h["company"],
                    "Role": h["role"],
                    "Decision": h["decision"],
                    "Confirmed": "Yes" if h["confirmed_checkbox"] else "No",
                    "Resume Path": h["resume_path"],
                    "Notes": h["reviewer_notes"],
                    "Timestamp": h["timestamp"],
                }
                for h in history
            ]
        )
        st.dataframe(hist_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No approval decisions recorded yet.")


# ============================================================================
# PAGE G: APPLICATION TRACKER
# ============================================================================
elif selected_page == "G. Application Tracker":
    st.header("📈 G. Application Tracker & Exporter")
    st.write("Track company, role, URL, applied date, status, and follow-up date. Export to Excel (.xlsx) and CSV.")

    status_filter = st.selectbox(
        "Filter by Application Status",
        ["All", "Submitted", "Under Review", "Interview", "Offer", "Rejected"],
    )

    apps = db.get_applications(status_filter=status_filter)
    df_apps = applications_to_dataframe(apps)

    ecol1, ecol2, _ = st.columns([1, 1, 2])
    with ecol1:
        csv_bytes = export_applications_to_csv(apps)
        st.download_button(
            label="📥 Export to CSV",
            data=csv_bytes,
            file_name="internship_applications.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with ecol2:
        excel_bytes = export_applications_to_excel(apps)
        st.download_button(
            label="📊 Export to Excel (.xlsx)",
            data=excel_bytes,
            file_name="internship_applications.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    st.dataframe(df_apps, use_container_width=True, hide_index=True)

    if apps:
        st.subheader("🔄 Update Application Status or Follow-Up Date")
        with st.form("update_tracker_status_form"):
            ucol1, ucol2, ucol3, ucol4 = st.columns(4)
            app_choices = {a["id"]: f"#{a['id']} - {a['company']} ({a['role']})" for a in apps}
            with ucol1:
                sel_app_id = st.selectbox(
                    "Select Application",
                    options=list(app_choices.keys()),
                    format_func=lambda x: app_choices[x],
                )
            current_app = next((a for a in apps if a["id"] == sel_app_id), apps[0])
            with ucol2:
                new_st = st.selectbox(
                    "New Status",
                    ["Submitted", "Under Review", "Interview", "Offer", "Rejected"],
                    index=["Submitted", "Under Review", "Interview", "Offer", "Rejected"].index(
                        current_app["status"]
                    )
                    if current_app["status"] in ["Submitted", "Under Review", "Interview", "Offer", "Rejected"]
                    else 0,
                )
            with ucol3:
                new_fup = st.text_input("Follow-Up Date (YYYY-MM-DD)", value=current_app.get("follow_up_date", ""))
            with ucol4:
                new_notes = st.text_input("Notes", value=current_app.get("notes", ""))

            if st.form_submit_button("💾 Update Tracker Record", type="primary"):
                db.update_application_status(sel_app_id, new_st, new_fup, new_notes)
                st.success(f"Updated Application #{sel_app_id} status to **{new_st}**!")
                st.rerun()


# ============================================================================
# PAGE H: SETTINGS
# ============================================================================
elif selected_page == "H. Settings":
    st.header("⚙️ H. System & Security Settings")
    st.write(
        "Configure search preferences, modular AI provider, daily discovery limits, allowed websites, and browser automation permissions."
    )

    with st.form("settings_configuration_form"):
        st.subheader("1. Search & Discovery Preferences")
        pref_roles_str = st.text_area(
            "Target Internship Roles (comma-separated)",
            value=", ".join(settings.preferred_roles),
        )
        pref_locs_str = st.text_input(
            "Preferred Locations (comma-separated)",
            value=", ".join(settings.preferred_locations),
        )
        daily_lim = st.number_input(
            "Daily Discovery Limit",
            min_value=1,
            max_value=500,
            value=int(settings.daily_discovery_limit),
        )

        st.subheader("2. Modular AI Provider Configuration")
        s_col1, s_col2, s_col3 = st.columns(3)
        with s_col1:
            ai_prov = st.selectbox(
                "AI Provider",
                ["none", "gemini", "openai", "groq"],
                index=["none", "gemini", "openai", "groq"].index(settings.ai_provider)
                if settings.ai_provider in ["none", "gemini", "openai", "groq"]
                else 0,
                help="Select 'none' for 100% local deterministic TF-IDF matching & fact-grounded templates without external API keys.",
            )
        with s_col2:
            ai_mod = st.text_input("Model Name", value=settings.ai_model)
        with s_col3:
            use_st = st.checkbox(
                "Enable Sentence-Transformers Dense Embeddings",
                value=settings.use_sentence_transformers,
            )

        k_col1, k_col2, k_col3 = st.columns(3)
        with k_col1:
            gemini_key = st.text_input(
                "GEMINI_API_KEY (Optional, saved to .env)",
                value="",
                type="password",
                placeholder="Leave blank to keep existing",
            )
        with k_col2:
            openai_key = st.text_input(
                "OPENAI_API_KEY (Optional, saved to .env)",
                value="",
                type="password",
                placeholder="Leave blank to keep existing",
            )
        with k_col3:
            groq_key = st.text_input(
                "GROQ_API_KEY (Optional, saved to .env)",
                value="",
                type="password",
                placeholder="Leave blank to keep existing",
            )

        st.subheader("3. Allowed Websites, Persistent Browser Profile & Terms Compliance")
        profile_dir_input = st.text_input(
            "Dedicated Persistent Browser Profile Directory (Private AppData Path)",
            value=settings.persistent_profile_dir,
            help="Stores your manual browser sign-in sessions locally in your private AppData folder. Never share passwords, OTPs, or cookies with the AI.",
        )
        allowed_doms_str = st.text_area(
            "Permitted & Terms-Verified Domains for Browser Automation (comma-separated; LinkedIn & Indeed are prohibited)",
            value=", ".join(settings.allowed_domains),
        )
        st.caption(
            "🚫 **Terms-Prohibited Automation Domains (Enforced):** `linkedin.com`, `indeed.com`, `indeed.co.in` — "
            "Applications on these platforms automatically generate a Direct Application URL and a Prepared Application Package for manual completion."
        )

        b_col1, b_col2, b_col3, b_col4 = st.columns(4)
        with b_col1:
            visible_mode = st.checkbox(
                "Run Browser in Visible Mode (Required for Manual Sign-In)",
                value=not settings.browser_headless,
            )
            headless_mode = not visible_mode
        with b_col2:
            pause_captcha = st.checkbox("Pause on CAPTCHA", value=settings.pause_on_captcha)
        with b_col3:
            pause_auth = st.checkbox("Pause on Login / MFA", value=settings.pause_on_auth)
        with b_col4:
            allow_upload = st.checkbox("Allow Resume File Upload", value=settings.allow_file_upload)

        st.checkbox(
            "Require Explicit Human Approval Before Any Submission (Always Enforced)",
            value=True,
            disabled=True,
        )

        st.subheader("4. Email Notification Preferences & Gmail SMTP / OAuth2 Integration")
        em_col1, em_col2, em_col3 = st.columns(3)
        with em_col1:
            email_enabled = st.checkbox(
                "Enable Email Notifications",
                value=settings.email_notifications_enabled,
            )
            recipient_addr = st.text_input(
                "Recipient Email Address (Registered Email)",
                value=settings.recipient_email,
            )
        with em_col2:
            smtp_host_val = st.text_input("SMTP Server Host", value=settings.smtp_host)
            smtp_port_val = st.number_input("SMTP Port", min_value=1, max_value=65535, value=int(settings.smtp_port))
        with em_col3:
            auth_method_val = st.selectbox(
                "Authentication Method",
                ["app_password", "oauth2"],
                index=0 if settings.email_auth_method == "app_password" else 1,
            )
            smtp_tls_val = st.checkbox("Use STARTTLS", value=settings.smtp_use_tls)

        ec_col1, ec_col2, ec_col3 = st.columns(3)
        with ec_col1:
            smtp_sender_input = st.text_input(
                "SMTP_SENDER_EMAIL (Saved to .env)",
                value=os.getenv("SMTP_SENDER_EMAIL", ""),
                placeholder="your_email@gmail.com",
            )
        with ec_col2:
            smtp_app_pwd_input = st.text_input(
                "SMTP_APP_PASSWORD (16-char Gmail App Password, saved to .env)",
                value="",
                type="password",
                placeholder="Leave blank to keep existing",
            )
        with ec_col3:
            smtp_oauth_input = st.text_input(
                "SMTP_OAUTH_ACCESS_TOKEN (Optional OAuth2 Bearer Token)",
                value="",
                type="password",
                placeholder="Leave blank to keep existing",
            )

        st.markdown("**Notification Event Triggers:**")
        nt_c1, nt_c2, nt_c3, nt_c4, nt_c5 = st.columns(5)
        with nt_c1:
            n_sub_ok = st.checkbox("Submission Confirmed", value=settings.notify_on_submission_success)
        with nt_c2:
            n_sub_fail = st.checkbox("Submission Failures", value=settings.notify_on_submission_failure)
        with nt_c3:
            n_await = st.checkbox("Awaiting Approval", value=settings.notify_on_awaiting_approval)
        with nt_c4:
            n_high = st.checkbox("High-Match Digest", value=settings.notify_on_high_match)
        with nt_c5:
            n_inter = st.checkbox("Interview / Status Updates", value=settings.notify_on_interview_status)

        if st.form_submit_button("💾 Save Configuration", type="primary"):
            cleaned_domains = [
                d.strip()
                for d in allowed_doms_str.split(",")
                if d.strip() and "linkedin.com" not in d.lower() and "indeed." not in d.lower()
            ]
            new_settings = AppSettings(
                ai_provider=ai_prov,
                ai_model=ai_mod,
                use_sentence_transformers=use_st,
                embedding_model=settings.embedding_model,
                database_path=settings.database_path,
                daily_discovery_limit=int(daily_lim),
                preferred_roles=[r.strip() for r in pref_roles_str.split(",") if r.strip()],
                preferred_locations=[l.strip() for l in pref_locs_str.split(",") if l.strip()],
                enabled_platforms=settings.enabled_platforms,
                allowed_domains=cleaned_domains,
                terms_verified_domains=cleaned_domains,
                persistent_profile_dir=profile_dir_input.strip(),
                browser_headless=headless_mode,
                browser_timeout_ms=settings.browser_timeout_ms,
                require_human_approval=True,
                pause_on_captcha=pause_captcha,
                pause_on_auth=pause_auth,
                allow_file_upload=allow_upload,
                email_notifications_enabled=email_enabled,
                recipient_email=recipient_addr.strip(),
                smtp_host=smtp_host_val.strip(),
                smtp_port=int(smtp_port_val),
                smtp_use_tls=smtp_tls_val,
                email_auth_method=auth_method_val,
                notify_on_submission_success=n_sub_ok,
                notify_on_submission_failure=n_sub_fail,
                notify_on_awaiting_approval=n_await,
                notify_on_high_match=n_high,
                notify_on_interview_status=n_inter,
            )
            save_settings(
                new_settings,
                api_keys={
                    "GEMINI_API_KEY": gemini_key,
                    "OPENAI_API_KEY": openai_key,
                    "GROQ_API_KEY": groq_key,
                    "SMTP_SENDER_EMAIL": smtp_sender_input,
                    "SMTP_APP_PASSWORD": smtp_app_pwd_input,
                    "SMTP_OAUTH_ACCESS_TOKEN": smtp_oauth_input,
                },
            )
            st.success("Configuration saved to `data/settings.json` and `.env`!")
            st.rerun()

    st.divider()
    st.subheader("📨 Email Delivery Diagnostics & Send Test Email")
    email_diag = email_service.get_configuration_status()
    d_col1, d_col2 = st.columns([2, 1])
    with d_col1:
        st.info(
            f"**Delivery Status:** `{email_diag['status_label']}`\n\n"
            f"- **Recipient Email:** `{email_diag['recipient_email']}`\n"
            f"- **Sender Email:** `{email_diag['sender_email']}`\n"
            f"- **SMTP Endpoint:** `{email_diag['smtp_host']}:{email_diag['smtp_port']}` (`{email_diag['auth_method']}`)"
        )
    with d_col2:
        if st.button("📧 Send Test Email", type="primary", use_container_width=True):
            test_res = email_service.send_test_email(custom_recipient=settings.recipient_email)
            if test_res.get("sent"):
                st.success(f"✅ {test_res['message']} (Status: `{test_res['delivery_status']}`)")
            else:
                st.warning(f"⚠️ {test_res['message']} (Status: `{test_res['delivery_status']}`)")

    email_logs = db.get_email_notifications(limit=25)
    if email_logs:
        st.markdown("**📜 SQLite Email Notification Audit Log (`email_notifications` table):**")
        log_df = pd.DataFrame(
            [
                {
                    "ID": l["id"],
                    "Event Type": l["event_type"],
                    "Recipient": l["recipient_email"],
                    "Subject": l["subject"],
                    "Company": l["company"],
                    "Tracking ID": l["tracking_id"],
                    "Delivery Status": l["delivery_status"],
                    "Attempts": l["attempts"],
                    "Timestamp": l["created_at"],
                }
                for l in email_logs
            ]
        )
        st.dataframe(log_df, use_container_width=True, hide_index=True)
