"""Unit and integration test suite for AI Internship Application Agent."""
from pathlib import Path
import pytest

from src.ai_engine import AIIntelligenceEngine
from src.browser_automation import BrowserAutomationEngine
from src.config import AppSettings
from src.database import DatabaseManager
from src.export_utils import export_applications_to_csv, export_applications_to_excel
from src.job_discovery import JobDiscoveryEngine
from src.models import ApplicationDraft, JobListing
from src.resume_parser import ResumeParser, extract_skills_from_text
from src.sample_data import generate_mock_portals, generate_sample_resumes


def test_pdf_and_docx_resume_parsing():
    """Verify PDF and DOCX resume extraction and fact-only skill/education/project parsing."""
    pdf_path, docx_path = generate_sample_resumes()
    assert pdf_path.exists()
    assert docx_path.exists()

    pdf_profile = ResumeParser.parse_file(pdf_path, profile_name="PDF Test")
    docx_profile = ResumeParser.parse_file(docx_path, profile_name="DOCX Test")

    assert "AARAV SHARMA" in pdf_profile.full_name.upper()
    assert pdf_profile.email == "aarav.sharma.ai@example.com"
    assert "Python" in pdf_profile.skills
    assert "LangChain" in pdf_profile.skills
    assert "PyTorch" in pdf_profile.skills
    assert len(pdf_profile.education) >= 1
    assert len(pdf_profile.projects) >= 1
    assert len(pdf_profile.experience) >= 1

    assert docx_profile.email == "aarav.sharma.ai@example.com"
    assert "Python" in docx_profile.skills
    assert "Agentic AI" in docx_profile.skills


def test_ai_job_matching_and_zero_hallucination_cover_letter():
    """Verify semantic job matching, missing skill detection, and fact-grounded cover letter generation."""
    pdf_path, _ = generate_sample_resumes()
    resume = ResumeParser.parse_file(pdf_path)

    job = JobListing(
        id=1,
        title="Agentic AI Developer Intern",
        company="TestCorp AI",
        location="Remote",
        stipend="₹45,000 / month",
        platform="Official Career Page",
        role_category="Agentic AI Developer",
        application_url="file:///test_portal.html",
        description=(
            "Seeking an Agentic AI Developer Intern with Python, LangChain, LangGraph, RAG, "
            "Kubernetes, and C++ experience."
        ),
        required_skills=["Python", "LangChain", "LangGraph", "RAG", "Kubernetes", "C++"],
    )

    engine = AIIntelligenceEngine(AppSettings(ai_provider="none", use_sentence_transformers=False))
    match = engine.evaluate_job_compatibility(resume, job)

    assert 0.0 <= match.overall_score <= 100.0
    assert "Python" in match.matched_skills
    assert "LangChain" in match.matched_skills
    assert "Kubernetes" in match.missing_skills
    assert "C++" in match.missing_skills

    # Verify cover letter never claims missing skills like Kubernetes or C++ as candidate skills
    cover_letter = engine.generate_cover_letter(resume, job, match)
    assert "TestCorp AI" in cover_letter
    assert "Agentic AI Developer Intern" in cover_letter
    assert resume.full_name in cover_letter
    assert "Kubernetes" not in cover_letter
    assert "C++" not in cover_letter


def test_database_workflow_approval_and_duplicate_prevention(tmp_path: Path):
    """Verify full database lifecycle: resume -> job -> match -> draft -> approval -> duplicate block -> export."""
    db_file = tmp_path / "test_agent.db"
    db = DatabaseManager(str(db_file))

    pdf_path, _ = generate_sample_resumes()
    resume = ResumeParser.parse_file(pdf_path)
    rid = db.save_resume_profile(resume)
    assert rid > 0

    discovery = JobDiscoveryEngine(daily_limit=10)
    jobs = discovery.discover_opportunities(role="Agentic AI Developer")
    assert len(jobs) >= 1

    jid, is_new = db.upsert_job_listing(jobs[0])
    assert is_new is True
    jid_dup, is_new_dup = db.upsert_job_listing(jobs[0])
    assert is_new_dup is False
    assert jid == jid_dup

    saved_job = db.get_job_by_id(jid)
    active_res = db.get_active_resume()
    engine = AIIntelligenceEngine()

    match = engine.evaluate_job_compatibility(active_res, saved_job)
    mid = db.save_job_match(match)
    assert mid > 0

    cl = engine.generate_cover_letter(active_res, saved_job, match)
    fa = engine.prepare_form_answers(active_res, saved_job, cl)

    draft = ApplicationDraft(
        job_id=jid,
        resume_id=rid,
        cover_letter=cl,
        form_Payload=fa,
        resume_file_path=str(pdf_path),
        automation_status="Form Filled (Awaiting Human Approval)",
        status="Pending Approval",
    )
    did = db.save_application_draft(draft)
    assert did > 0

    # Submitting without explicit checkbox confirmation must raise ValueError
    with pytest.raises(ValueError):
        db.approve_and_record_submission(draft_id=did, confirmed_checkbox=False)

    # Submitting with explicit human confirmation must succeed and record tracker & audit trail
    app_id = db.approve_and_record_submission(
        draft_id=did,
        reviewer_notes="Unit test verified approval",
        confirmed_checkbox=True,
    )
    assert app_id > 0

    # Duplicate application must be blocked
    assert db.has_already_applied(jid) is True
    with pytest.raises(ValueError):
        db.save_application_draft(draft)

    # Test MARK AS MANUALLY SUBMITTED on a second job (e.g., LinkedIn / Indeed restricted listing)
    jid2, _ = db.upsert_job_listing(jobs[1])
    draft2 = ApplicationDraft(
        job_id=jid2,
        resume_id=rid,
        cover_letter=cl,
        form_Payload=fa,
        resume_file_path=str(pdf_path),
        automation_status="Manual Completion Required (PROHIBITED_BY_TERMS)",
        status="Pending Approval",
    )
    did2 = db.save_application_draft(draft2)
    assert did2 > 0

    # Unconfirmed manual submission must raise ValueError
    with pytest.raises(ValueError):
        db.mark_as_manually_submitted(draft_id=did2, confirmed_checkbox=False)

    # Confirmed manual submission must update SQLite only, record date & MANUALLY_SUBMITTED audit log, and prevent duplicates
    man_app_id = db.mark_as_manually_submitted(
        draft_id=did2,
        reviewer_notes="Submitted manually on restricted platform",
        confirmed_checkbox=True,
        submission_date="2026-11-20",
    )
    assert man_app_id > 0
    with pytest.raises(ValueError):
        db.mark_as_manually_submitted(draft_id=did2, confirmed_checkbox=True)

    history = db.get_approval_history()
    decisions = [h["decision"] for h in history]
    assert "APPROVED_AND_SUBMITTED" in decisions
    assert "MANUALLY_SUBMITTED" in decisions

    # Verify overview metrics
    metrics = db.get_overview_metrics()
    assert metrics["total_discovered"] == 2
    assert metrics["applications_prepared"] == 2
    assert metrics["applications_submitted"] == 2

    # Verify CSV and Excel exports
    apps = db.get_applications()
    csv_bytes = export_applications_to_csv(apps, save_path=tmp_path / "out.csv")
    xlsx_bytes = export_applications_to_excel(apps, save_path=tmp_path / "out.xlsx")
    assert len(csv_bytes) > 20
    assert len(xlsx_bytes) > 100


def test_playwright_browser_safety_and_local_portal_autofill(tmp_path: Path):
    """Verify all 14 Playwright requirements: persistent profile, visible mode, LinkedIn/Indeed block, terms check,
    login/CAPTCHA pause, stop before submit, manual application package fallback, and Emergency Stop button."""
    generate_mock_portals()
    pdf_path, _ = generate_sample_resumes()
    browser_eng = BrowserAutomationEngine()
    BrowserAutomationEngine.reset_emergency_stop()

    # 1. Dedicated persistent browser profile in private AppData directory & visible mode default (Reqs 1 & 2)
    profile_dir = browser_eng.get_persistent_profile_dir()
    assert profile_dir.exists()
    assert "AIInternshipAgent" in str(profile_dir)
    assert browser_eng.settings.browser_headless is False

    # 2. LinkedIn & Indeed prohibition + Terms of Service checks (Reqs 7, 8 & 14)
    assert browser_eng.is_url_allowed("https://evil-untrusted-domain.example.org/apply") is False
    assert browser_eng.is_url_allowed("https://www.linkedin.com/jobs/view/123") is False
    assert browser_eng.is_url_allowed("https://in.indeed.com/viewjob?jk=456") is False
    assert browser_eng.is_url_allowed("https://boards.greenhouse.io/company/jobs/789") is True

    li_terms = browser_eng.check_platform_terms_compliance("https://www.linkedin.com/jobs/view/123", "LinkedIn")
    assert li_terms["automation_permitted"] is False
    assert li_terms["policy_status"] == "PROHIBITED_BY_TERMS"

    indeed_res = browser_eng.inspect_and_fill_application(
        url="https://in.indeed.com/viewjob?jk=456",
        form_payload={"full_name": "Aarav Sharma", "email": "aarav@example.com"},
        resume_file_path=str(pdf_path),
        company="InsightGrid",
        role="Data Scientist Intern",
        platform="Indeed",
    )
    assert indeed_res["success"] is False
    assert indeed_res["submitted"] is False
    assert indeed_res["manual_package"] is not None
    assert Path(indeed_res["manual_package"]["package_md_path"]).exists()
    assert Path(indeed_res["manual_package"]["package_json_path"]).exists()

    # 3. Automatic submission without explicit_human_approval must raise PermissionError (Reqs 10 & 12)
    with pytest.raises(PermissionError):
        browser_eng.inspect_and_fill_application(
            url="file:///dummy.html",
            form_payload={"full_name": "Test"},
            submit_after_fill=True,
            explicit_human_approval=False,
        )

    # 4. Login page and CAPTCHA detection tests (Reqs 4, 5 & 6)
    captcha_html = "<html><body><div class='g-recaptcha'>Verify you are human</div></body></html>"
    gates = browser_eng._detect_security_gates_in_html(captcha_html, "https://example.com")
    assert gates["has_captcha"] is True
    assert gates["requires_human_intervention"] is True

    login_html = "<html><body><form><input type='password' name='pwd'/>Sign in to continue</form></body></html>"
    login_gates = browser_eng._detect_security_gates_in_html(login_html, "https://example.com/login")
    assert login_gates["has_auth_wall"] is True
    assert login_gates["requires_human_intervention"] is True

    # 5. Safe form filling on permitted career portal stopping before final Submit (Reqs 9, 10, 11)
    portal_url = (Path("data/mock_portals/portal_agentic_ai.html").resolve()).as_uri()
    payload = {
        "full_name": "Aarav Sharma",
        "email": "aarav.sharma.ai@example.com",
        "phone": "+91 98765 43210",
        "current_location": "Bangalore, India",
        "linkedin_url": "https://linkedin.com/in/aarav-sharma-ai",
        "github_url": "https://github.com/aarav-sharma-ai",
        "degree": "B.Tech in CS (AI & ML)",
        "institution": "IIIT Bangalore",
        "gpa": "8.9/10",
        "availability": "Immediate",
        "primary_skills": "Python, LangGraph, PyTorch, FastAPI",
        "why_this_role": "Strong alignment with multi-agent systems.",
        "cover_letter": "Dear Hiring Team, please find my application attached.",
    }
    res = browser_eng.inspect_and_fill_application(
        url=portal_url,
        form_payload=payload,
        resume_file_path=str(pdf_path),
        submit_after_fill=False,
        explicit_human_approval=False,
    )
    assert res["success"] is True
    assert res["submitted"] is False
    assert "full_name" in res["filled_fields"]
    assert res["filled_fields"]["resume_file"] == pdf_path.name
    assert Path(res["screenshot_path"]).exists()

    # 6. Emergency Stop Browser button test
    stop_info = BrowserAutomationEngine.emergency_stop_browser()
    assert stop_info["stopped"] is True
    stopped_res = browser_eng.inspect_and_fill_application(
        url=portal_url,
        form_payload=payload,
        resume_file_path=str(pdf_path),
    )
    assert stopped_res["success"] is False
    assert "Emergency Stop" in stopped_res["status"]
    assert stopped_res["manual_package"] is not None
    BrowserAutomationEngine.reset_emergency_stop()


def test_source_url_verification_and_daily_scheduled_pipeline():
    """Verify real source URL classification, clear labeling of unverified/demo listings, and daily discovery pipeline."""
    from src.daily_automation import run_daily_discovery_pipeline

    ver_real = JobDiscoveryEngine.classify_source_verification(
        "https://www.sarvam.ai/careers", "https://www.sarvam.ai/careers"
    )
    assert ver_real["is_verified_source"] is True
    assert "VERIFIED" in ver_real["verification_status"]

    ver_demo = JobDiscoveryEngine.classify_source_verification(
        "file:///C:/portal_agentic_ai.html", "file:///C:/portal_agentic_ai.html"
    )
    assert ver_demo["is_verified_source"] is False
    assert "UNVERIFIED" in ver_demo["verification_status"]

    ver_unknown = JobDiscoveryEngine.classify_source_verification(
        "https://unknown-random-site.example.org/jobs/1"
    )
    assert ver_unknown["is_verified_source"] is False
    assert "UNVERIFIED" in ver_unknown["verification_status"]

    # Run daily pipeline and verify top 20 ranking, verified source labeling, and 0 auto-submissions
    res = run_daily_discovery_pipeline(top_k=20, prepare_top_n_drafts=3)
    assert res["success"] is True
    assert res["summary"]["auto_submitted_count"] == 0
    assert len(res["top_20_opportunities"]) == 20
    assert Path(res["report_md_path"]).exists()
    assert Path(res["report_json_path"]).exists()

    # Confirm both verified real career URLs and clearly labeled unverified demo portals are tracked
    verified_count = sum(1 for item in res["top_20_opportunities"] if item["is_verified_source"])
    unverified_count = sum(1 for item in res["top_20_opportunities"] if not item["is_verified_source"])
    assert verified_count >= 10
    assert unverified_count >= 1


def test_email_notifications_and_windows_launchpad(tmp_path: Path):
    """Test Feature 1 (Email Notification System) and Feature 2 (Windows Launchpad & Desktop Shortcut)."""
    from src.email_notifications import EmailNotificationService
    from src.windows_launchpad import (
        BATCH_LAUNCHER_PATH,
        LOCAL_SHORTCUT_PATH,
        create_windows_desktop_shortcuts,
    )

    db_file = tmp_path / "test_email.db"
    db = DatabaseManager(str(db_file))
    cfg = AppSettings(
        database_path=str(db_file),
        email_notifications_enabled=True,
        recipient_email="sauravtiwari2712005@gmail.com",
    )
    email_svc = EmailNotificationService(db=db, settings=cfg)

    # 1. Email configuration check
    status = email_svc.get_configuration_status()
    assert status["enabled"] is True
    assert status["recipient_email"] == "sauravtiwari2712005@gmail.com"

    # 2. Test email delivery
    test_res = email_svc.send_test_email()
    assert test_res["sent"] is True
    assert Path(test_res["eml_path"]).exists()

    # 3. Guardrail: Never send a successful-submission email merely because a draft was prepared
    with pytest.raises(ValueError):
        email_svc.send_submission_confirmation_email(
            company="DraftOnlyCorp",
            role="AI Engineer Intern",
            platform="Official Career Page",
            application_url="https://example.com/apply",
            resume_used="Saurav_Kumar_Resume (1).pdf",
            application_status="Draft Prepared",
            tracking_id=101,
            submission_mode="DRAFT_ONLY",
        )

    # 4. Successful-submission notification (portal_confirmed=True)
    sub_res = email_svc.send_submission_confirmation_email(
        company="SimPortal AI",
        role="Agentic AI Developer Intern",
        platform="Official Career Page",
        application_url="file:///simulated_portal.html",
        resume_used="resumes/Saurav_Kumar_Resume (1).pdf",
        application_status="Submitted",
        tracking_id=202,
        submission_mode="AUTOMATED",
        portal_confirmed=True,
    )
    assert sub_res["sent"] is True
    assert sub_res["subject"] == "Internship Application Successfully Submitted – SimPortal AI"
    eml_text = Path(sub_res["eml_path"]).read_text(encoding="utf-8")
    assert "SimPortal AI" in eml_text
    assert "Agentic AI Developer Intern" in eml_text
    assert "APP-202" in eml_text
    assert "Saurav_Kumar_Resume (1).pdf" in eml_text

    # 5. Duplicate email prevention
    dup_res = email_svc.send_submission_confirmation_email(
        company="SimPortal AI",
        role="Agentic AI Developer Intern",
        platform="Official Career Page",
        application_url="file:///simulated_portal.html",
        resume_used="resumes/Saurav_Kumar_Resume (1).pdf",
        application_status="Submitted",
        tracking_id=202,
        submission_mode="AUTOMATED",
        portal_confirmed=True,
    )
    assert dup_res["sent"] is False
    assert dup_res["duplicate_prevented"] is True
    assert dup_res["delivery_status"] == "DUPLICATE_PREVENTED"

    # 6. Pending verification labeling when portal confirmation is False
    pend_res = email_svc.send_submission_confirmation_email(
        company="UnverifiedPortal Corp",
        role="ML Intern",
        platform="Official Career Page",
        application_url="https://example.com/jobs/1",
        resume_used="resumes/Saurav_Kumar_Resume (1).pdf",
        application_status="Pending Verification",
        tracking_id=203,
        submission_mode="AUTOMATED",
        portal_confirmed=False,
    )
    assert pend_res["sent"] is True
    assert "Pending Verification" in pend_res["subject"]

    # 7. Manual-submission notification (requires explicit_manual_mark=True)
    with pytest.raises(ValueError):
        email_svc.send_submission_confirmation_email(
            company="LinkedIn Manual Corp",
            role="GenAI Intern",
            platform="LinkedIn",
            application_url="https://linkedin.com/jobs/view/1",
            resume_used="resumes/Saurav_Kumar_Resume (1).pdf",
            application_status="Submitted",
            tracking_id=204,
            submission_mode="MANUAL",
            explicit_manual_mark=False,
        )

    man_res = email_svc.send_submission_confirmation_email(
        company="LinkedIn Manual Corp",
        role="GenAI Intern",
        platform="LinkedIn",
        application_url="https://linkedin.com/jobs/view/1",
        resume_used="resumes/Saurav_Kumar_Resume (1).pdf",
        application_status="Submitted",
        tracking_id=204,
        submission_mode="MANUAL",
        explicit_manual_mark=True,
    )
    assert man_res["sent"] is True
    assert man_res["subject"] == "Internship Application Successfully Submitted – LinkedIn Manual Corp"

    # 8. Failed-submission notification
    fail_res = email_svc.send_submission_failure_notification(
        company="CaptchaGate Corp",
        role="Data Science Intern",
        platform="Official Career Page",
        application_url="https://example.com/apply",
        error_reason="CAPTCHA detected on application page.",
        draft_id=55,
    )
    assert fail_res["sent"] is True
    assert "Failed" in fail_res["subject"]

    # Verify all events logged in SQLite email_notifications table
    logs = db.get_email_notifications()
    assert len(logs) >= 5

    # 9. Verify Windows Batch Launcher (launch_dashboard.bat) and Desktop Shortcut (.lnk)
    sc_info = create_windows_desktop_shortcuts()
    assert BATCH_LAUNCHER_PATH.exists()
    bat_content = BATCH_LAUNCHER_PATH.read_text(encoding="utf-8")
    assert "streamlit run app.py" in bat_content
    assert ":8501" in bat_content
    assert LOCAL_SHORTCUT_PATH.exists()
    assert LOCAL_SHORTCUT_PATH.stat().st_size > 70

    # 10. Verify Windows Task Scheduler XML & daily run summary email notification
    from src.windows_scheduler import BATCH_RUNNER_PATH, generate_task_scheduler_xml

    xml_path = generate_task_scheduler_xml()
    assert xml_path.exists()
    xml_text = xml_path.read_bytes().decode("utf-16")
    assert "T09:00:00" in xml_text
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml_text
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml_text
    assert "<RestartOnFailure>" in xml_text
    assert BATCH_RUNNER_PATH.exists()

    summary_email = email_svc.send_daily_run_summary_email(
        jobs_discovered=24,
        verified_opportunities=17,
        matching_opportunities=23,
        drafts_prepared_this_run=5,
        total_awaiting_approval=5,
        execution_status="SUCCESS",
        start_time="2026-11-20 09:00:00 IST",
        completion_time="2026-11-20 09:00:06 IST",
        dashboard_url="http://localhost:8501",
    )
    assert summary_email["sent"] is True
    assert "Daily Discovery Summary" in summary_email["subject"]
    assert "5 Drafts Awaiting Your Approval" in summary_email["subject"]
