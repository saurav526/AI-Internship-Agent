# 🤖 AI Internship Application Agent

A complete, human-in-the-loop **AI Internship Application Agent** built with **Python**, **Streamlit**, **SQLite**, **Playwright**, **PyMuPDF**, **python-docx**, **scikit-learn**, **Sentence Transformers**, and **Pydantic**.
---

## 🌟 Core Capabilities

1. **Multi-Format Resume Parser (`src/resume_parser.py`)**
   - Extracts raw text and structured profile fields (contact info, education, skills, projects, experience) from **PDF** (`PyMuPDF`) and **DOCX** (`python-docx`) resumes.
   - Allows full interactive editing and approval before saving to SQLite.
   - **Zero-Hallucination Policy:** Never fabricates qualifications, degrees, or experience not present in your resume.

2. **Legitimate Job Discovery (`src/job_discovery.py`)**
   - Targets 7 core internship roles:
     - **AI Engineer**
     - **Agentic AI Developer**
     - **Generative AI Engineer**
     - **Machine Learning Engineer**
     - **Data Scientist**
     - **LLM Engineer**
     - **Python Developer**
   - Covers 6 target platforms: **LinkedIn**, **Internshala**, **Wellfound**, **Naukri**, **Indeed**, and **Official Company Career Pages**.
   - Uses legitimate public listings, curated local feeds (`data/sample_jobs.json`), and authorized public RSS/JSON APIs without bypassing login walls, rate limits, or CAPTCHAs.

3. **AI Job Matching & Compatibility Engine (`src/ai_engine.py`)**
   - Computes multi-factor compatibility scores:
     - **Skill Overlap Score (50%)**
     - **Semantic Similarity Score (30%)** via `scikit-learn` TF-IDF cosine similarity or optional `Sentence-Transformers` (`all-MiniLM-L6-v2`) dense embeddings
     - **Role Alignment Score (20%)**
   - Identifies **Matched Skills**, explains **Missing Skills**, and ranks opportunities.
   - Modular LLM provider interface (`BaseLLMProvider`) supporting **Google Gemini**, **OpenAI**, **Groq**, and a **100% Local Deterministic Non-LLM Fallback** that works out-of-the-box without API keys.

4. **Playwright Browser Automation & Safe Form Pre-Filling (`src/browser_automation.py`)**
   - Initializes headless or headed Chromium via Playwright.
   - Navigates to allowed domains or local HTML portals (`data/mock_portals/*.html`).
   - Detects form inputs, fills verified candidate fields, uploads the selected PDF/DOCX resume, and captures full-page proof screenshots (`outputs/screenshots/`).
   - **Mandatory Safety Gates:**
     - Automatically pauses for human intervention if **Authentication/Login**, **CAPTCHA**, **MFA/2FA**, or **uncertain fields** are detected.
     - Never stores plaintext passwords or authentication cookies.
     - **Never submits automatically.**

5. **Approval Center & Application Tracker (`app.py`, `src/database.py`, `src/export_utils.py`)**
   - Displays all prepared form values, cover letter, uploaded resume file, and pre-fill screenshots.
   - Requires checking an **explicit confirmation checkbox** before clicking **Approve and Submit** or **Reject**.
   - Prevents duplicate applications at the SQLite level.
   - Exports tracked applications to **Excel (`.xlsx`)** and **CSV (`.csv`)**.

---

## 🗂️ Project Architecture

```text
AI-Internship-Agent/
├── app.py                          # Primary 8-page Streamlit Dashboard
├── requirements.txt                # Python dependencies
├── .env.example                    # Example environment configuration
├── .env                            # Active environment configuration
├── README.md                       # Windows setup & execution guide
├── src/
│   ├── __init__.py
│   ├── config.py                   # Pydantic AppSettings & .env persistence
│   ├── logger.py                   # Console + rotating file logger (logs/agent.log)
│   ├── models.py                   # Pydantic domain schemas
│   ├── database.py                 # SQLite repository (6 tables + duplicate prevention)
│   ├── resume_parser.py            # PDF (PyMuPDF) & DOCX (python-docx) parser
│   ├── ai_engine.py                # Modular LLM providers, semantic matcher & cover letters
│   ├── job_discovery.py            # Legitimate job discovery & public feed adapters
│   ├── browser_automation.py       # Playwright form detector, filler, uploader & screenshots
│   ├── export_utils.py             # Excel (.xlsx) & CSV exporter
│   └── sample_data.py              # Generates sample PDF/DOCX resumes & local HTML portals
├── tests/
│   └── test_agent.py               # Pytest unit & integration test suite
├── data/
│   ├── internship_agent.db         # SQLite database (auto-created)
│   ├── sample_jobs.json            # Curated public internship listings
│   └── mock_portals/               # Local HTML internship application forms for safe testing
├── resumes/
│   ├── sample_ai_engineer_resume.pdf
│   └── sample_ai_engineer_resume.docx
├── outputs/
│   ├── screenshots/                # Playwright pre-fill & submission proof screenshots
│   └── exports/                    # Exported CSV and Excel tracker reports
└── logs/
    └── agent.log                   # Application execution logs
```

---

## 🪟 Windows Setup & Execution Commands

Open **PowerShell** in `C:\Users\Asus\Downloads\AI-Internship-Agent` and run:

### 1. Install Dependencies (if needed)
```powershell
python -m pip install -r requirements.txt
playwright install chromium
```

### 2. Configure Environment (Optional)
```powershell
Copy-Item .env.example .env -ErrorAction SilentlyContinue
```

### 3. Run the Unit & Integration Test Suite
```powershell
python -m pytest tests/test_agent.py -v
```

### 4. Launch the Streamlit Dashboard
```powershell
python -m streamlit run app.py
```

The dashboard will open at **http://localhost:8501**.

---

## 🔑 Features That Work Locally vs. Optional External API Credentials

| Feature | Works 100% Locally (No API Key) | Optional External API Enhancement |
| :--- | :--- | :--- |
| **Resume Parsing (PDF & DOCX)** | ✅ Yes (`PyMuPDF` & `python-docx`) | Not required |
| **Job Discovery & Filtering** | ✅ Yes (Curated feed + public Remotive API/RSS) | Not required |
| **Semantic Job Matching & Scoring** | ✅ Yes (`scikit-learn` TF-IDF + `Sentence-Transformers`) | Not required |
| **Missing Skill Analysis & Ranking** | ✅ Yes (Canonical 40+ AI/ML/Python taxonomy) | Not required |
| **Customized Cover Letter Generation** | ✅ Yes (Fact-grounded deterministic generator) | Optional `GEMINI_API_KEY`, `OPENAI_API_KEY`, or `GROQ_API_KEY` in `.env` or Page H (Settings) |
| **Playwright Form Pre-Fill & Resume Upload** | ✅ Yes (Local Chromium + safe test portals) | Real external job boards with login walls pause for manual user sign-in |
| **Approval Center & Excel/CSV Export** | ✅ Yes (`SQLite` + `openpyxl` + `pandas`) | Not required |
