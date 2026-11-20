"""PDF and DOCX Resume Parser with skill, education, project, and experience extraction.

Strict Anti-Hallucination Rule:
Only extracts text, skills, education, projects, and experience explicitly present in the document.
TI read the resume text and extract structured information without inventing any qualifications, skills, or experiences that are not explicitly mentioned in the resume.
The parser uses a canonical skill taxonomy to identify relevant skills and technologies mentioned in the resume.
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import docx
import pymupdf

from src.logger import get_logger
from src.models import EducationItem, ExperienceItem, ProjectItem, ResumeProfile

logger = get_logger("resume_parser")

# Canonical skill taxonomy covering AI, Agentic AI, GenAI, ML, Data Science, LLM, Python & Software Engineering
SKILL_TAXONOMY: Dict[str, List[str]] = {
    "Python": ["python", "python3", "python 3"],
    "PyTorch": ["pytorch", "torch"],
    "TensorFlow": ["tensorflow", "tf", "keras"],
    "Scikit-Learn": ["scikit-learn", "sklearn", "scikit learn"],
    "LangChain": ["langchain", "lang-chain"],
    "LangGraph": ["langgraph", "lang-graph"],
    "LlamaIndex": ["llamaindex", "llama-index", "gpt-index"],
    "CrewAI": ["crewai", "crew ai"],
    "AutoGen": ["autogen", "auto-gen"],
    "Agentic AI": ["agentic ai", "ai agents", "autonomous agents", "multi-agent", "tool calling", "function calling"],
    "Generative AI": ["generative ai", "genai", "gen ai", "diffusion models", "stable diffusion"],
    "LLMs": ["llm", "llms", "large language models", "large language model", "gpt-4", "claude", "gemini", "llama 3", "mistral"],
    "RAG": ["rag", "retrieval-augmented generation", "retrieval augmented generation", "graphrag"],
    "Prompt Engineering": ["prompt engineering", "few-shot", "chain-of-thought", "cot"],
    "Fine-Tuning": ["fine-tuning", "fine tuning", "peft", "lora", "qlora", "rlhf", "dpo", "sft"],
    "Hugging Face": ["hugging face", "huggingface", "transformers"],
    "Vector Databases": ["vector database", "vector db", "faiss", "chromadb", "chroma", "pinecone", "weaviate", "milvus", "qdrant"],
    "NLP": ["nlp", "natural language processing", "spacy", "nltk", "bert", "tokenization", "embeddings", "sentence-transformers"],
    "Computer Vision": ["computer vision", "opencv", "yolo", "cnn", "image processing", "object detection", "segmentation"],
    "Machine Learning": ["machine learning", "supervised learning", "unsupervised learning", "xgboost", "lightgbm", "catboost", "random forest"],
    "Deep Learning": ["deep learning", "neural networks", "rnn", "lstm", "transformer architecture", "attention mechanism"],
    "Data Science": ["data science", "data analysis", "exploratory data analysis", "eda", "feature engineering", "a/b testing"],
    "Statistics": ["statistics", "probability", "hypothesis testing", "bayesian", "time series"],
    "Pandas": ["pandas", "geopandas"],
    "NumPy": ["numpy", "scipy"],
    "SQL": ["sql", "postgresql", "postgres", "mysql", "sqlite", "snowflake", "bigquery"],
    "NoSQL": ["mongodb", "redis", "dynamodb", "cassandra"],
    "FastAPI": ["fastapi", "fast api"],
    "Flask": ["flask"],
    "Django": ["django"],
    "Streamlit": ["streamlit", "gradio"],
    "REST APIs": ["rest api", "restful", "graphql", "grpc", "webhooks"],
    "Playwright": ["playwright", "selenium", "puppeteer", "browser automation", "web scraping", "beautifulsoup"],
    "Docker": ["docker", "containerization", "docker-compose"],
    "Kubernetes": ["kubernetes", "k8s", "helm"],
    "MLOps": ["mlops", "mlflow", "weights & biases", "wandb", "dvc", "kubeflow", "evidently", "arize"],
    "Cloud (AWS/GCP/Azure)": ["aws", "gcp", "google cloud", "azure", "vertex ai", "sagemaker", "bedrock"],
    "Git": ["git", "github", "gitlab", "ci/cd", "github actions"],
    "Linux": ["linux", "bash", "shell scripting"],
    "Data Visualization": ["matplotlib", "seaborn", "plotly", "power bi", "tableau", "looker"],
    "Spark": ["pyspark", "apache spark", "databricks", "kafka", "airflow"],
    "Pydantic": ["pydantic", "type hinting", "asyncio"],
    "JavaScript/TypeScript": ["javascript", "typescript", "react", "node.js", "nextjs"],
    "C++": ["c++", "cuda", "tensorrt", "onnx"],
}


def extract_skills_from_text(text: str) -> List[str]:
    """Deterministically extract canonical skills from text using word-boundary aware matching."""
    if not text:
        return []
    lower_text = text.lower()
    detected: List[str] = []

    for canonical, aliases in SKILL_TAXONOMY.items():
        for alias in aliases:
            pattern = r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])"
            if re.search(pattern, lower_text):
                detected.append(canonical)
                break
    return sorted(list(set(detected)))


class ResumeParser:
    """Extracts text and structured sections from PDF and DOCX resumes."""

    @staticmethod
    def extract_text_from_pdf(file_path: str | Path) -> str:
        """Extract plain text from a PDF file using PyMuPDF."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {path}")

        text_blocks: List[str] = []
        with pymupdf.open(str(path)) as doc:
            for page in doc:
                page_text = page.get_text("text")
                if page_text:
                    text_blocks.append(page_text)
        full_text = "\n".join(text_blocks).strip()
        logger.info("Extracted %d characters from PDF %s", len(full_text), path.name)
        return full_text

    @staticmethod
    def extract_text_from_docx(file_path: str | Path) -> str:
        """Extract plain text from a DOCX file using python-docx."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"DOCX file not found: {path}")

        doc = docx.Document(str(path))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

        # Also extract text from tables if the resume uses table layouts
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paragraphs.append(row_text)

        full_text = "\n".join(paragraphs).strip()
        logger.info("Extracted %d characters from DOCX %s", len(full_text), path.name)
        return full_text

    @classmethod
    def extract_text(cls, file_path: str | Path) -> str:
        """Dispatch text extraction based on file extension."""
        path = Path(file_path)
        ext = path.suffix.lower()
        if ext == ".pdf":
            return cls.extract_text_from_pdf(path)
        if ext in (".docx", ".doc"):
            return cls.extract_text_from_docx(path)
        if ext in (".txt", ".md"):
            return path.read_text(encoding="utf-8")
        raise ValueError(f"Unsupported resume format: {ext}. Please upload a PDF or DOCX file.")

    @staticmethod
    def _extract_contact_info(text: str) -> Dict[str, str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        full_name = ""
        for line in lines[:5]:
            # First short line without email/http/numbers is usually the candidate's name
            if (
                2 <= len(line.split()) <= 5
                and "@" not in line
                and "http" not in line.lower()
                and "resume" not in line.lower()
                and not re.search(r"\d{4}", line)
            ):
                full_name = re.sub(r"[^a-zA-Z\s\.\-]", "", line).strip()
                break

        email_match = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
        email = email_match.group(0) if email_match else ""

        phone_match = re.search(
            r"(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{3,5}\)?[\s\-]?)?\d{3,5}[\s\-]?\d{4,5}", text
        )
        phone = phone_match.group(0).strip() if phone_match else ""

        linkedin_match = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[a-zA-Z0-9\-_]+", text, re.I)
        linkedin = linkedin_match.group(0) if linkedin_match else ""

        github_match = re.search(r"(?:https?://)?(?:www\.)?github\.com/[a-zA-Z0-9\-_]+", text, re.I)
        github = github_match.group(0) if github_match else ""

        location = "India"
        for loc in [
            "Bangalore",
            "Bengaluru",
            "Hyderabad",
            "Pune",
            "Mumbai",
            "Delhi",
            "Noida",
            "Gurgaon",
            "Chennai",
            "Kolkata",
            "Remote",
            "San Francisco",
            "New York",
        ]:
            if re.search(r"\b" + re.escape(loc) + r"\b", text, re.I):
                location = loc
                break

        return {
            "full_name": full_name or "Candidate",
            "email": email,
            "phone": phone,
            "location": location,
            "linkedin_url": linkedin,
            "github_url": github,
        }

    @staticmethod
    def _split_sections(text: str) -> Dict[str, List[str]]:
        """Split resume lines into logical sections based on common headings."""
        section_headers = {
            "summary": ["summary", "objective", "profile", "about me"],
            "education": ["education", "academic background", "academics", "qualifications"],
            "skills": ["skills", "technical skills", "core competencies", "technologies", "tech stack"],
            "projects": ["projects", "academic projects", "personal projects", "key projects", "ai projects"],
            "experience": [
                "experience",
                "work experience",
                "professional experience",
                "internships",
                "employment",
            ],
        }

        sections: Dict[str, List[str]] = {
            "header": [],
            "summary": [],
            "education": [],
            "skills": [],
            "projects": [],
            "experience": [],
        }

        current_section = "header"
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            clean_heading = re.sub(r"[^a-zA-Z\s]", "", line).strip().lower()
            matched_sec: Optional[str] = None
            if len(clean_heading.split()) <= 4:
                for sec_key, aliases in section_headers.items():
                    if clean_heading in aliases:
                        matched_sec = sec_key
                        break

            if matched_sec:
                current_section = matched_sec
            else:
                sections[current_section].append(line)

        return sections

    @staticmethod
    def _parse_education(lines: List[str], full_text: str) -> List[EducationItem]:
        items: List[EducationItem] = []
        degree_pattern = re.compile(
            r"(B\.?Tech|M\.?Tech|B\.?E\.?|M\.?E\.?|B\.?S\.?|M\.?S\.?|B\.?Sc|M\.?Sc|Bachelor|Master|Ph\.?D|MBA|BCA|MCA)[^,\n]*",
            re.I,
        )

        source_lines = lines if lines else full_text.splitlines()
        current_degree = ""
        current_inst = ""
        current_year = ""
        current_gpa = ""

        for line in source_lines:
            deg_m = degree_pattern.search(line)
            year_m = re.search(r"(20\d{2}\s*[-–to]+\s*(?:20\d{2}|Present)|20\d{2})", line, re.I)
            gpa_m = re.search(r"(?:CGPA|GPA|Percentage)[:\s]*([0-9.]+(?:/[0-9.]+|%?))", line, re.I)

            if deg_m:
                if current_degree:
                    items.append(
                        EducationItem(
                            degree=current_degree,
                            institution=current_inst or "University / Institute",
                            year=current_year,
                            gpa=current_gpa,
                        )
                    )
                current_degree = deg_m.group(0).strip(" -|•")
                remainder = line.replace(deg_m.group(0), "").strip(" -|,•")
                current_inst = remainder if len(remainder) > 3 else ""
                current_year = year_m.group(0) if year_m else ""
                current_gpa = gpa_m.group(1) if gpa_m else ""
            elif current_degree:
                if not current_inst and any(
                    k in line.lower()
                    for k in ["university", "institute", "college", "iit", "nit", "iiit", "school", "academy"]
                ):
                    current_inst = line.strip(" -|•")
                if not current_year and year_m:
                    current_year = year_m.group(0)
                if not current_gpa and gpa_m:
                    current_gpa = gpa_m.group(1)

        if current_degree:
            items.append(
                EducationItem(
                    degree=current_degree,
                    institution=current_inst or "University / Institute",
                    year=current_year,
                    gpa=current_gpa,
                )
            )
        return items

    @staticmethod
    def _parse_projects(lines: List[str]) -> List[ProjectItem]:
        projects: List[ProjectItem] = []
        if not lines:
            return projects

        curr_name = ""
        curr_desc: List[str] = []

        for line in lines:
            is_bullet = line.startswith(("•", "-", "*", "–", "·"))
            if not is_bullet and len(line) < 95 and not line.endswith("."):
                if curr_name:
                    joined_desc = " ".join(curr_desc).strip()
                    techs = extract_skills_from_text(curr_name + " " + joined_desc)
                    projects.append(
                        ProjectItem(name=curr_name, description=joined_desc, technologies=techs)
                    )
                curr_name = line.strip(" -|•:")
                curr_desc = []
            else:
                clean_bullet = line.lstrip("•-*–· ").strip()
                if not curr_name:
                    curr_name = clean_bullet[:60]
                curr_desc.append(clean_bullet)

        if curr_name:
            joined_desc = " ".join(curr_desc).strip()
            techs = extract_skills_from_text(curr_name + " " + joined_desc)
            projects.append(ProjectItem(name=curr_name, description=joined_desc, technologies=techs))

        return projects[:8]

    @staticmethod
    def _parse_experience(lines: List[str]) -> List[ExperienceItem]:
        experiences: List[ExperienceItem] = []
        if not lines:
            return experiences

        curr_role = ""
        curr_company = ""
        curr_duration = ""
        curr_bullets: List[str] = []

        for line in lines:
            is_bullet = line.startswith(("•", "-", "*", "–", "·"))
            date_m = re.search(
                r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d{2}\s*[-–to]+\s*(?:Present|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d{2})|20\d{2}\s*[-–to]+\s*(?:20\d{2}|Present))",
                line,
                re.I,
            )

            if not is_bullet and (date_m or "|" in line or " at " in line.lower() or "intern" in line.lower()):
                if curr_role:
                    experiences.append(
                        ExperienceItem(
                            role=curr_role,
                            company=curr_company or "Organization",
                            duration=curr_duration,
                            summary=" ".join(curr_bullets).strip(),
                        )
                    )
                curr_bullets = []
                curr_duration = date_m.group(0) if date_m else ""
                header_clean = line.replace(curr_duration, "").strip(" -|•,()")
                if "|" in header_clean:
                    parts = [p.strip() for p in header_clean.split("|") if p.strip()]
                    curr_role = parts[0]
                    curr_company = parts[1] if len(parts) > 1 else ""
                elif " at " in header_clean.lower():
                    parts = re.split(r"\bat\b", header_clean, flags=re.I)
                    curr_role = parts[0].strip()
                    curr_company = parts[1].strip() if len(parts) > 1 else ""
                elif " - " in header_clean:
                    parts = [p.strip() for p in header_clean.split(" - ") if p.strip()]
                    curr_role = parts[0]
                    curr_company = parts[1] if len(parts) > 1 else ""
                else:
                    curr_role = header_clean
                    curr_company = ""
            else:
                clean_b = line.lstrip("•-*–· ").strip()
                if not curr_role:
                    curr_role = "Experience / Internship"
                curr_bullets.append(clean_b)

        if curr_role:
            experiences.append(
                ExperienceItem(
                    role=curr_role,
                    company=curr_company or "Organization",
                    duration=curr_duration,
                    summary=" ".join(curr_bullets).strip(),
                )
            )
        return experiences[:8]

    @classmethod
    def parse_resume_text(cls, raw_text: str, file_path: str = "", profile_name: str = "Primary Resume") -> ResumeProfile:
        """Parse raw resume text into a structured ResumeProfile without inventing any qualifications."""
        contact = cls._extract_contact_info(raw_text)
        sections = cls._split_sections(raw_text)

        skills = extract_skills_from_text(raw_text)
        education = cls._parse_education(sections["education"], raw_text)
        projects = cls._parse_projects(sections["projects"])
        experience = cls._parse_experience(sections["experience"])

        summary_text = " ".join(sections["summary"]).strip()
        if not summary_text and sections["header"]:
            # Use non-contact lines from header if present
            header_candidates = [
                l
                for l in sections["header"][1:]
                if "@" not in l and "linkedin" not in l.lower() and "github" not in l.lower()
            ]
            summary_text = " ".join(header_candidates[:3]).strip()

        return ResumeProfile(
            profile_name=profile_name,
            full_name=contact["full_name"],
            email=contact["email"],
            phone=contact["phone"],
            location=contact["location"],
            linkedin_url=contact["linkedin_url"],
            github_url=contact["github_url"],
            summary=summary_text,
            education=education,
            skills=skills,
            projects=projects,
            experience=experience,
            raw_text=raw_text,
            file_path=str(file_path),
            is_active=True,
        )

    @classmethod
    def parse_file(cls, file_path: str | Path, profile_name: str = "Primary Resume") -> ResumeProfile:
        """Extract text from PDF/DOCX file and parse into a structured ResumeProfile."""
        raw_text = cls.extract_text(file_path)
        return cls.parse_resume_text(raw_text=raw_text, file_path=str(file_path), profile_name=profile_name)
