"""Pydantic data models for AI Internship Application Agent."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class EducationItem(BaseModel):
    degree: str = ""
    institution: str = ""
    year: str = ""
    gpa: str = ""


class ProjectItem(BaseModel):
    name: str = ""
    description: str = ""
    technologies: List[str] = Field(default_factory=list)


class ExperienceItem(BaseModel):
    role: str = ""
    company: str = ""
    duration: str = ""
    summary: str = ""


class ResumeProfile(BaseModel):
    id: Optional[int] = None
    profile_name: str = "Primary Resume"
    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    summary: str = ""
    education: List[EducationItem] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    projects: List[ProjectItem] = Field(default_factory=list)
    experience: List[ExperienceItem] = Field(default_factory=list)
    raw_text: str = ""
    file_path: str = ""
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class JobListing(BaseModel):
    id: Optional[int] = None
    job_uid: str = ""
    title: str
    company: str
    location: str = "Remote"
    stipend: str = "Unpaid / Not Disclosed"
    platform: str = "Official Career Page"
    role_category: str = "AI Engineer"
    application_url: str
    source_url: str = ""
    is_verified_source: bool = True
    verification_status: str = "VERIFIED_PUBLIC_SOURCE"  # VERIFIED_LIVE_API, VERIFIED_CAREER_PAGE, VERIFIED_LOCAL_PORTAL, UNVERIFIED_LISTING
    description: str = ""
    required_skills: List[str] = Field(default_factory=list)
    posted_date: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    is_saved: bool = True
    discovered_at: Optional[str] = None


class JobMatch(BaseModel):
    id: Optional[int] = None
    job_id: int
    resume_id: int
    overall_score: float = Field(ge=0.0, le=100.0)
    skill_score: float = Field(ge=0.0, le=100.0)
    semantic_score: float = Field(ge=0.0, le=100.0)
    role_alignment_score: float = Field(ge=0.0, le=100.0)
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    explanation: str = ""
    recommendation: str = "Strong Match"
    evaluated_at: Optional[str] = None


class ApplicationDraft(BaseModel):
    id: Optional[int] = None
    job_id: int
    resume_id: int
    cover_letter: str = ""
    form_Payload: Dict[str, Any] = Field(default_factory=dict)
    resume_file_path: str = ""
    automation_status: str = "Draft Saved"  # Draft Saved, Form Filled (Awaiting Approval), Ready for Approval, Paused (Human Intervention)
    screenshot_path: str = ""
    detected_fields: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "Pending Approval"  # Pending Approval, Approved & Submitted, Rejected
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ApplicationRecord(BaseModel):
    id: Optional[int] = None
    job_id: int
    draft_id: Optional[int] = None
    resume_id: int
    company: str
    role: str
    platform: str
    application_url: str
    applied_date: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    status: str = "Submitted"  # Prepared, Submitted, Under Review, Interview, Offer, Rejected
    follow_up_date: str = ""
    notes: str = ""
    screenshot_path: str = ""
    created_at: Optional[str] = None


class ApprovalHistoryItem(BaseModel):
    id: Optional[int] = None
    draft_id: int
    job_id: int
    company: str
    role: str
    decision: str  # APPROVED_AND_SUBMITTED, REJECTED
    reviewer_notes: str = ""
    confirmed_checkbox: bool = True
    form_snapshot: Dict[str, Any] = Field(default_factory=dict)
    resume_path: str = ""
    timestamp: Optional[str] = None
