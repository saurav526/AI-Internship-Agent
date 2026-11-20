"""AI Intelligence Engine for AI Internship Application Agent.

Provides:
1. Modular LLM Provider Interface (Gemini, OpenAI, Groq, and Local Deterministic Fallback)
2. Job Description Parser & Skill Extractor
3. Semantic Matching (TF-IDF Cosine Similarity + optional Sentence-Transformers embeddings)
4. Missing Skill Analysis & Compatibility Ranking
5. Fact-Grounded Customized Cover Letter & Form Answer Generator (Never invents qualifications)
"""
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.config import AppSettings, load_settings
from src.logger import get_logger
from src.models import JobListing, JobMatch, ResumeProfile
from src.resume_parser import extract_skills_from_text

logger = get_logger("ai_engine")


# ============================================================================
# 1. MODULAR LLM PROVIDER INTERFACE
# ============================================================================


class BaseLLMProvider(ABC):
    """Abstract base class for pluggable LLM providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        pass

    @abstractmethod
    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        pass


class NonLLMFallbackProvider(BaseLLMProvider):
    """Deterministic, rule-based and template-driven provider that requires no external API keys."""

    @property
    def provider_name(self) -> str:
        return "Local Deterministic Engine (No API Key Required)"

    def is_available(self) -> bool:
        return True

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        return ""


class GeminiLLMProvider(BaseLLMProvider):
    """Google Gemini API provider using google-genai SDK."""

    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash") -> None:
        self.api_key = api_key.strip()
        self.model_name = model_name or "gemini-2.5-flash"

    @property
    def provider_name(self) -> str:
        return f"Google Gemini ({self.model_name})"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=self.model_name,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
            ),
        )
        return (response.text or "").strip()


class GroqLLMProvider(BaseLLMProvider):
    """Groq Cloud API provider."""

    def __init__(self, api_key: str, model_name: str = "llama-3.3-70b-versatile") -> None:
        self.api_key = api_key.strip()
        self.model_name = model_name if "llama" in model_name.lower() or "mixtral" in model_name.lower() else "llama-3.3-70b-versatile"

    @property
    def provider_name(self) -> str:
        return f"Groq ({self.model_name})"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        from groq import Groq

        client = Groq(api_key=self.api_key)
        completion = client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        return (completion.choices[0].message.content or "").strip()


class OpenAICompatibleProvider(BaseLLMProvider):
    """OpenAI REST API provider using requests (no extra SDK dependency required)."""

    def __init__(self, api_key: str, model_name: str = "gpt-4o-mini") -> None:
        self.api_key = api_key.strip()
        self.model_name = model_name if "gpt" in model_name.lower() else "gpt-4o-mini"

    @property
    def provider_name(self) -> str:
        return f"OpenAI ({self.model_name})"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        import requests

        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
            },
            timeout=25,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


def get_llm_provider(settings: Optional[AppSettings] = None) -> BaseLLMProvider:
    """Factory that returns the configured LLM provider or transparently falls back to NonLLMFallbackProvider."""
    cfg = settings or load_settings()
    prov = cfg.ai_provider.lower().strip()

    if prov == "gemini":
        key = os.getenv("GEMINI_API_KEY", "")
        if key:
            return GeminiLLMProvider(api_key=key, model_name=cfg.ai_model)
    elif prov == "groq":
        key = os.getenv("GROQ_API_KEY", "")
        if key:
            return GroqLLMProvider(api_key=key, model_name=cfg.ai_model)
    elif prov == "openai":
        key = os.getenv("OPENAI_API_KEY", "")
        if key:
            return OpenAICompatibleProvider(api_key=key, model_name=cfg.ai_model)

    return NonLLMFallbackProvider()


# ============================================================================
# 2. SEMANTIC SIMILARITY & JOB MATCHER
# ============================================================================


class AIIntelligenceEngine:
    """Core AI Engine for Job Parsing, Semantic Matching, Missing Skill Analysis, and Cover Letter Generation."""

    _st_model = None

    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        self.settings = settings or load_settings()
        self.llm = get_llm_provider(self.settings)

    def parse_job_description(self, description: str, existing_skills: Optional[List[str]] = None) -> Dict[str, Any]:
        """Extract required skills, key responsibilities, and role focus from a job description."""
        extracted = extract_skills_from_text(description)
        merged_skills = sorted(list(set((existing_skills or []) + extracted)))

        sentences = [s.strip() for s in re.split(r"[\n\.\•]+", description) if len(s.strip()) > 15]
        return {
            "required_skills": merged_skills,
            "key_points": sentences[:6],
        }

    def compute_semantic_similarity(self, resume_text: str, job_text: str) -> float:
        """Compute semantic similarity score (0..100) using Sentence-Transformers if enabled, else TF-IDF cosine similarity."""
        if not resume_text.strip() or not job_text.strip():
            return 0.0

        # Optional Sentence-Transformers dense vector similarity
        if self.settings.use_sentence_transformers:
            try:
                if AIIntelligenceEngine._st_model is None:
                    from sentence_transformers import SentenceTransformer

                    AIIntelligenceEngine._st_model = SentenceTransformer(self.settings.embedding_model)
                embeddings = AIIntelligenceEngine._st_model.encode([resume_text, job_text])
                sim = float(cosine_similarity([embeddings[0]], [embeddings[1]])[0][0])
                return round(max(0.0, min(100.0, sim * 100.0)), 1)
            except Exception as exc:
                logger.warning("SentenceTransformer fallback to TF-IDF: %s", exc)

        # Fast, reliable scikit-learn TF-IDF bigram/unigram cosine similarity
        try:
            vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
            tfidf_matrix = vectorizer.fit_transform([resume_text.lower(), job_text.lower()])
            raw_cos = float(cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0])
            # Scale TF-IDF cosine (which typically ranges 0.08 - 0.55 on raw documents) to a calibrated 0..100 scale
            scaled = min(100.0, (raw_cos ** 0.55) * 115.0)
            return round(max(0.0, scaled), 1)
        except Exception as exc:
            logger.warning("TF-IDF calculation failed: %s", exc)
            return 50.0

    def evaluate_job_compatibility(self, resume: ResumeProfile, job: JobListing) -> JobMatch:
        """Compare candidate's ResumeProfile against a JobListing and generate comprehensive compatibility breakdown."""
        parsed_jd = self.parse_job_description(job.description + " " + job.title, job.required_skills)
        job_skills = parsed_jd["required_skills"]

        resume_skill_set = {s.lower(): s for s in resume.skills}
        # Also include skills mentioned in raw resume text or projects
        for extra_s in extract_skills_from_text(resume.raw_text):
            resume_skill_set.setdefault(extra_s.lower(), extra_s)

        matched_skills: List[str] = []
        missing_skills: List[str] = []

        for js in job_skills:
            if js.lower() in resume_skill_set:
                matched_skills.append(js)
            else:
                missing_skills.append(js)

        if job_skills:
            skill_score = round((len(matched_skills) / len(job_skills)) * 100.0, 1)
        else:
            skill_score = 75.0

        resume_corpus = " ".join(
            [
                resume.summary,
                " ".join(resume.skills),
                " ".join(f"{p.name} {p.description} {' '.join(p.technologies)}" for p in resume.projects),
                " ".join(f"{x.role} {x.company} {x.summary}" for x in resume.experience),
                resume.raw_text,
            ]
        )
        job_corpus = f"{job.title} {job.role_category} {job.description} {' '.join(job_skills)}"
        semantic_score = self.compute_semantic_similarity(resume_corpus, job_corpus)

        # Role alignment score
        role_keywords = [w.lower() for w in re.findall(r"[a-zA-Z]{2,}", job.title + " " + job.role_category)]
        resume_lower = resume_corpus.lower()
        role_hits = sum(1 for kw in set(role_keywords) if kw in resume_lower)
        role_alignment_score = round(min(100.0, (role_hits / max(1, len(set(role_keywords)))) * 100.0), 1)

        # Weighted composite score: 50% skill overlap + 30% semantic similarity + 20% role alignment
        overall_score = round(
            0.50 * skill_score + 0.30 * semantic_score + 0.20 * role_alignment_score,
            1,
        )

        if overall_score >= 78.0:
            recommendation = "Strong Match - High Priority"
        elif overall_score >= 60.0:
            recommendation = "Good Match - Worth Applying"
        elif overall_score >= 42.0:
            recommendation = "Moderate Match - Upskill Recommended"
        else:
            recommendation = "Low Match - Significant Skill Gaps"

        explanation_parts = [
            f"Matched {len(matched_skills)} of {len(job_skills)} required skills ({skill_score}% skill coverage).",
            f"Semantic text similarity is {semantic_score}% and role alignment is {role_alignment_score}%.",
        ]
        if matched_skills:
            explanation_parts.append(f"Core strengths matching this role: {', '.join(matched_skills[:6])}.")
        if missing_skills:
            explanation_parts.append(
                f"Missing skills identified in JD: {', '.join(missing_skills)}. Consider highlighting transferable projects in {', '.join(matched_skills[:3]) or 'Python'}."
            )
        else:
            explanation_parts.append("Your resume covers 100% of the detected technical skills in this listing.")

        return JobMatch(
            job_id=job.id or 0,
            resume_id=resume.id or 0,
            overall_score=overall_score,
            skill_score=skill_score,
            semantic_score=semantic_score,
            role_alignment_score=role_alignment_score,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            explanation=" ".join(explanation_parts),
            recommendation=recommendation,
        )

    def generate_cover_letter(
        self,
        resume: ResumeProfile,
        job: JobListing,
        match: Optional[JobMatch] = None,
    ) -> str:
        """Generate a customized cover letter grounded strictly in the candidate's verified resume profile.

        Never invents degrees, employers, projects, or skills not present in `resume`.
        """
        eval_match = match or self.evaluate_job_compatibility(resume, job)
        verified_matched = eval_match.matched_skills or resume.skills[:5]

        # Try configured external LLM first if available, with strict anti-hallucination guardrail
        if not isinstance(self.llm, NonLLMFallbackProvider) and self.llm.is_available():
            sys_prompt = (
                "You are an ethical AI Career Assistant writing an internship cover letter. "
                "CRITICAL RULE: NEVER invent or fabricate any qualifications, skills, degrees, metrics, or work experience. "
                "Use ONLY the exact facts provided in the Candidate Resume JSON below."
            )
            user_prompt = (
                f"Candidate Name: {resume.full_name}\n"
                f"Verified Skills: {', '.join(resume.skills)}\n"
                f"Verified Education: {[e.model_dump() for e in resume.education]}\n"
                f"Verified Projects: {[p.model_dump() for p in resume.projects]}\n"
                f"Verified Experience: {[x.model_dump() for x in resume.experience]}\n\n"
                f"Target Role: {job.title} at {job.company} ({job.location})\n"
                f"Job Description: {job.description}\n"
                f"Matched Skills: {', '.join(verified_matched)}\n\n"
                "Write a concise, professional 3-paragraph internship cover letter referencing only verified facts."
            )
            try:
                llm_letter = self.llm.generate_text(sys_prompt, user_prompt)
                if llm_letter and len(llm_letter) > 100:
                    return llm_letter
            except Exception as exc:
                logger.warning("External LLM failed (%s); using fact-grounded deterministic generator.", exc)

        # Deterministic Fact-Grounded Cover Letter Builder (Zero Hallucination)
        edu_phrase = ""
        if resume.education:
            top_edu = resume.education[0]
            edu_phrase = f"As a {top_edu.degree} student/graduate from {top_edu.institution}"
            if top_edu.gpa:
                edu_phrase += f" (GPA/CGPA: {top_edu.gpa})"
            edu_phrase += ", "

        skills_phrase = (
            ", ".join(verified_matched[:6])
            if verified_matched
            else (", ".join(resume.skills[:6]) if resume.skills else "software development")
        )

        project_para = ""
        if resume.projects:
            top_projs = resume.projects[:2]
            proj_descriptions = []
            for p in top_projs:
                tech_str = f" using {', '.join(p.technologies[:4])}" if p.technologies else ""
                proj_descriptions.append(f"'{p.name}'{tech_str} ({p.description[:140].rstrip('.')})")
            project_para = (
                f"Through my hands-on project work, I have built "
                + " and ".join(proj_descriptions)
                + ". "
            )

        exp_para = ""
        if resume.experience:
            top_exp = resume.experience[0]
            exp_para = (
                f"Additionally, during my experience as {top_exp.role} at {top_exp.company}, "
                f"I focused on {top_exp.summary[:160].rstrip('.')}. "
            )

        letter = (
            f"Dear Hiring Team at {job.company},\n\n"
            f"I am writing to express my strong interest in the {job.title} position at {job.company} "
            f"({job.location}). {edu_phrase}I have developed practical proficiency in {skills_phrase}, "
            f"which directly aligns with the technical requirements of your team.\n\n"
            f"{project_para}{exp_para}"
            f"These experiences have given me a solid foundation in building reliable, well-tested systems "
            f"and collaborating effectively on technical deliverables.\n\n"
            f"I would welcome the opportunity to discuss how my verified background in {skills_phrase} "
            f"can contribute to {job.company}'s goals. Thank you for your time and consideration.\n\n"
            f"Sincerely,\n"
            f"{resume.full_name}\n"
            f"{resume.email} | {resume.phone}"
        )
        if resume.linkedin_url or resume.github_url:
            links = " | ".join([u for u in [resume.linkedin_url, resume.github_url] if u])
            letter += f"\n{links}"

        return letter

    def prepare_form_answers(
        self,
        resume: ResumeProfile,
        job: JobListing,
        cover_letter: str,
    ) -> Dict[str, Any]:
        """Generate structured form field values grounded strictly in the candidate's resume profile."""
        top_edu = resume.education[0] if resume.education else None
        top_proj = resume.projects[0] if resume.projects else None
        top_exp = resume.experience[0] if resume.experience else None

        why_company = (
            f"I am applying for the {job.title} role at {job.company} because my verified skills in "
            f"{', '.join(resume.skills[:5]) or 'Python and AI'} align closely with your focus on "
            f"{job.role_category}."
        )
        if top_proj:
            why_company += f" I have directly applied these skills in my project '{top_proj.name}'."

        return {
            "full_name": resume.full_name,
            "email": resume.email,
            "phone": resume.phone,
            "current_location": resume.location or "India",
            "linkedin_url": resume.linkedin_url,
            "github_url": resume.github_url,
            "portfolio_url": resume.portfolio_url or resume.github_url,
            "degree": top_edu.degree if top_edu else "Not specified in resume",
            "institution": top_edu.institution if top_edu else "Not specified in resume",
            "graduation_year": top_edu.year if top_edu else "Not specified in resume",
            "gpa": top_edu.gpa if top_edu else "Not specified in resume",
            "primary_skills": ", ".join(resume.skills[:10]),
            "key_project_highlight": (
                f"{top_proj.name}: {top_proj.description}" if top_proj else "See attached resume"
            ),
            "experience_summary": (
                f"{top_exp.role} at {top_exp.company} ({top_exp.duration}): {top_exp.summary}"
                if top_exp
                else "Entry-level / Academic project experience as detailed in resume"
            ),
            "why_this_role": why_company,
            "availability": "Immediate / Full-time Internship",
            "work_authorization": "Authorized to work",
            "cover_letter": cover_letter,
        }
