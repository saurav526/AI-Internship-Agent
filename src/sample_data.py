"""Sample data generator for AI Internship Application Agent.

Creates:
1. Sample PDF Resume (`resumes/sample_ai_engineer_resume.pdf`) using PyMuPDF
2. Sample DOCX Resume (`resumes/sample_ai_engineer_resume.docx`) using python-docx
3. Local Realistic Internship Application HTML Portals (`data/mock_portals/*.html`) for safe Playwright form filling
4. Initial database seed if the database is empty (without submitting any real applications)
"""
import json
from pathlib import Path
from typing import Tuple
import docx
import pymupdf

from src.ai_engine import AIIntelligenceEngine
from src.database import DatabaseManager
from src.job_discovery import JobDiscoveryEngine, SAMPLE_JOBS_PATH, get_default_curated_internships
from src.logger import get_logger
from src.resume_parser import ResumeParser

logger = get_logger("sample_data")

BASE_DIR = Path(__file__).resolve().parent.parent
RESUMES_DIR = BASE_DIR / "resumes"
PORTALS_DIR = BASE_DIR / "data" / "mock_portals"

SAMPLE_RESUME_LINES = [
    "AARAV SHARMA",
    "Bangalore, India | aarav.sharma.ai@example.com | +91 98765 43210",
    "https://linkedin.com/in/aarav-sharma-ai | https://github.com/aarav-sharma-ai",
    "",
    "SUMMARY",
    "Final-year Computer Science & Artificial Intelligence student specializing in Agentic AI, Generative AI, LLMs, RAG architectures, Machine Learning, and Python backend engineering.",
    "",
    "EDUCATION",
    "B.Tech in Computer Science and Engineering (AI & ML) - Indian Institute of Information Technology (IIIT), Bangalore | 2023 - 2027 | CGPA: 8.9/10",
    "",
    "SKILLS",
    "Python, PyTorch, Scikit-Learn, LangChain, LangGraph, LlamaIndex, CrewAI, Agentic AI, Generative AI, LLMs, RAG, Prompt Engineering, Hugging Face, Vector Databases, NLP, Machine Learning, Deep Learning, Data Science, Pandas, NumPy, SQL, FastAPI, Streamlit, Playwright, Pydantic, Docker, Git",
    "",
    "PROJECTS",
    "Autonomous Multi-Agent Research & Coding Assistant",
    "• Built a multi-agent orchestration system using Python, LangGraph, LangChain, CrewAI, and Pydantic with human-in-the-loop approval checkpoints.",
    "• Integrated FAISS and ChromaDB vector databases for hybrid RAG retrieval and exposed REST APIs via FastAPI and Streamlit.",
    "Enterprise RAG & Fine-Tuned LLM Evaluation Benchmark",
    "• Fine-tuned open-weights Llama-3 models with LoRA/PEFT using PyTorch and Hugging Face Transformers.",
    "• Automated hallucination detection and semantic similarity scoring using Sentence-Transformers and Scikit-Learn.",
    "Playwright Browser Automation & Intelligent Form Agent",
    "• Engineered a safe Playwright browser automation agent in Python with DOM inspection, screenshot capture, and SQLite state tracking.",
    "",
    "EXPERIENCE",
    "AI Engineering Intern | CogniVerse Labs | May 2025 - Aug 2025",
    "• Developed production RAG pipelines and LLM tool-calling agents in Python, reducing query latency by 35%.",
    "• Collaborated on FastAPI microservices, unit testing with pytest, and Docker deployment.",
    "Machine Learning Research Intern | DataPulse Analytics | Dec 2024 - Feb 2025",
    "• Built predictive classification models using Scikit-Learn, Pandas, NumPy, and SQL for time-series anomaly detection.",
]


def _build_portal_html(portal_title: str, company_name: str, role_title: str, theme_color: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <title>{company_name} - {role_title} Application Portal</title>
    <style>
        body {{
            font-family: 'Segoe UI', Roboto, Arial, sans-serif;
            background: #f4f7fb;
            color: #1e293b;
            margin: 0;
            padding: 32px;
        }}
        .container {{
            max-width: 780px;
            margin: 0 auto;
            background: #ffffff;
            border-radius: 12px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
            padding: 32px 40px;
            border-top: 6px solid {theme_color};
        }}
        .badge {{
            display: inline-block;
            background: #e0f2fe;
            color: #0369a1;
            padding: 4px 12px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 8px;
        }}
        h1 {{ margin: 4px 0 6px 0; font-size: 24px; color: #0f172a; }}
        p.sub {{ margin: 0 0 24px 0; color: #64748b; font-size: 14px; }}
        .grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }}
        .form-group {{
            margin-bottom: 16px;
        }}
        label {{
            display: block;
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 6px;
            color: #334155;
        }}
        input[type="text"], input[type="email"], input[type="tel"], input[type="url"], textarea {{
            width: 100%;
            box-sizing: border-box;
            padding: 10px 12px;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            font-size: 14px;
            background: #f8fafc;
        }}
        textarea {{ min-height: 110px; resize: vertical; }}
        .file-box {{
            padding: 14px;
            border: 2px dashed #94a3b8;
            border-radius: 8px;
            background: #f8fafc;
        }}
        .btn-submit {{
            background: {theme_color};
            color: #ffffff;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            margin-top: 12px;
        }}
        #submission-banner {{
            display: none;
            margin-top: 20px;
            padding: 16px;
            border-radius: 8px;
            background: #dcfce7;
            color: #166534;
            font-weight: 600;
            border: 1px solid #86efac;
        }}
    </style>
</head>
<body>
    <div class="container">
        <span class="badge">{portal_title}</span>
        <h1>{role_title}</h1>
        <p class="sub">{company_name} • Official Internship Application Form</p>

        <form id="internship-application-form" onsubmit="event.preventDefault(); document.getElementById('submission-banner').style.display='block';">
            <div class="grid">
                <div class="form-group">
                    <label for="full_name">Full Name *</label>
                    <input type="text" id="full_name" name="full_name" placeholder="Enter your full name" required />
                </div>
                <div class="form-group">
                    <label for="email">Email Address *</label>
                    <input type="email" id="email" name="email" placeholder="name@example.com" required />
                </div>
                <div class="form-group">
                    <label for="phone">Phone Number *</label>
                    <input type="tel" id="phone" name="phone" placeholder="+91 9876543210" required />
                </div>
                <div class="form-group">
                    <label for="current_location">Current Location *</label>
                    <input type="text" id="current_location" name="current_location" placeholder="City, Country" />
                </div>
                <div class="form-group">
                    <label for="linkedin_url">LinkedIn Profile URL</label>
                    <input type="url" id="linkedin_url" name="linkedin_url" placeholder="https://linkedin.com/in/..." />
                </div>
                <div class="form-group">
                    <label for="github_url">GitHub / Portfolio URL</label>
                    <input type="url" id="github_url" name="github_url" placeholder="https://github.com/..." />
                </div>
                <div class="form-group">
                    <label for="degree">Degree & Major</label>
                    <input type="text" id="degree" name="degree" placeholder="B.Tech in CS / AI" />
                </div>
                <div class="form-group">
                    <label for="institution">University / Institution</label>
                    <input type="text" id="institution" name="institution" placeholder="University Name" />
                </div>
                <div class="form-group">
                    <label for="gpa">CGPA / GPA</label>
                    <input type="text" id="gpa" name="gpa" placeholder="8.9/10" />
                </div>
                <div class="form-group">
                    <label for="availability">Availability / Start Date</label>
                    <input type="text" id="availability" name="availability" placeholder="Immediate" />
                </div>
            </div>

            <div class="form-group">
                <label for="primary_skills">Verified Technical Skills</label>
                <input type="text" id="primary_skills" name="primary_skills" placeholder="Python, PyTorch, LangChain..." />
            </div>

            <div class="form-group">
                <label for="why_this_role">Why are you interested in this internship?</label>
                <textarea id="why_this_role" name="why_this_role" placeholder="Share your relevant background..."></textarea>
            </div>

            <div class="form-group">
                <label for="cover_letter">Customized Cover Letter</label>
                <textarea id="cover_letter" name="cover_letter" placeholder="Paste your cover letter..."></textarea>
            </div>

            <div class="form-group">
                <label for="resume_upload">Upload Resume (PDF or DOCX) *</label>
                <div class="file-box">
                    <input type="file" id="resume_upload" name="resume_file" accept=".pdf,.docx" />
                </div>
            </div>

            <button type="submit" id="submit-application-btn" class="btn-submit">Submit Internship Application</button>
            <div id="submission-banner">
                ✔ Application Submitted Successfully! Confirmation Reference: #INT-2026-VERIFIED
            </div>
        </form>
    </div>
</body>
</html>
"""


def generate_mock_portals() -> None:
    """Create local HTML internship application portals for safe Playwright automation."""
    PORTALS_DIR.mkdir(parents=True, exist_ok=True)
    portals = [
        (
            "portal_agentic_ai.html",
            "Agentic AI & Python Portal",
            "AetherMind Autonomous Systems",
            "Agentic AI Developer Intern",
            "#2563eb",
        ),
        (
            "portal_genai_llm.html",
            "Generative AI & LLM Portal",
            "NovaSynth AI Labs",
            "Generative AI & LLM Engineer Intern",
            "#7c3aed",
        ),
        (
            "portal_ml_datascience.html",
            "Machine Learning & Data Science Portal",
            "QuantPulse Analytics",
            "Machine Learning & Data Scientist Intern",
            "#059669",
        ),
    ]
    for filename, badge, company, role, color in portals:
        path = PORTALS_DIR / filename
        path.write_text(_build_portal_html(badge, company, role, color), encoding="utf-8")


def generate_sample_resumes() -> Tuple[Path, Path]:
    """Generate both a sample PDF resume and a sample DOCX resume inside `resumes/`."""
    RESUMES_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = RESUMES_DIR / "sample_ai_engineer_resume.pdf"
    docx_path = RESUMES_DIR / "sample_ai_engineer_resume.docx"

    # 1. Generate PDF using PyMuPDF
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 45
    for idx, line in enumerate(SAMPLE_RESUME_LINES):
        if not line:
            y += 8
            continue
        fontsize = 15 if idx == 0 else (11.5 if line.isupper() and len(line) < 25 else 9.5)
        page.insert_text((45, y), line, fontsize=fontsize)
        y += 15 if fontsize > 10 else 13
    doc.save(str(pdf_path))
    doc.close()

    # 2. Generate DOCX using python-docx
    wdoc = docx.Document()
    for line in SAMPLE_RESUME_LINES:
        if line:
            wdoc.add_paragraph(line)
    wdoc.save(str(docx_path))

    return pdf_path, docx_path


def ensure_sample_environment(db: DatabaseManager) -> None:
    """Ensure mock portals, sample resumes, curated jobs, and initial resume/matches exist."""
    generate_mock_portals()
    pdf_path, _ = generate_sample_resumes()

    # Rewrite sample_jobs.json so portal file:// URIs match the current workspace path
    SAMPLE_JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SAMPLE_JOBS_PATH, "w", encoding="utf-8") as f:
        json.dump(get_default_curated_internships(), f, indent=2)

    # Seed active resume if none exists
    active_resume = db.get_active_resume()
    if not active_resume:
        profile = ResumeParser.parse_file(pdf_path, profile_name="Aarav Sharma - AI & Agentic Systems Resume")
        resume_id = db.save_resume_profile(profile)
        active_resume = db.get_active_resume()
        logger.info("Seeded default resume profile ID=%s", resume_id)

    # Seed or synchronize curated jobs so both verified real source URLs and labeled demo sandbox listings exist
    discovery = JobDiscoveryEngine()
    curated = discovery.load_curated_feed()
    for job in curated:
        db.upsert_job_listing(job)
    existing_jobs = db.get_job_listings()
    logger.info("Synchronized %d curated internship listings.", len(existing_jobs))

    # Compute initial AI job matches if none exist
    if active_resume and existing_jobs:
        existing_matches = db.get_ranked_matches(active_resume.id)
        if not existing_matches:
            engine = AIIntelligenceEngine()
            for job in existing_jobs:
                match = engine.evaluate_job_compatibility(active_resume, job)
                db.save_job_match(match)
            logger.info("Computed initial compatibility matches for %d jobs.", len(existing_jobs))
