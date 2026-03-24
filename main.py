from __future__ import annotations

import re
import sqlite3
import os
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from statistics import mean
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from docx import Document
from pydantic import BaseModel, Field
from pypdf import PdfReader
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import LLM abstraction layer
from llm_provider import generate_with_llm, extract_json_from_llm_response, LLMFactory


app = FastAPI(
    title="Career CoPilot MVP API",
    version="0.1.0",
    description="Career Audit + Action Plan API",
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = Path("/tmp/career_copilot.db") if os.getenv("VERCEL") else BASE_DIR / "career_copilot.db"
CLAUDE_MODEL = "claude-3-5-sonnet-20241022"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@dataclass
class SalaryBand:
    min_lpa: float
    max_lpa: float


ROLE_BANDS = {
    "frontend engineer": SalaryBand(18, 42),
    "backend engineer": SalaryBand(20, 48),
    "full stack engineer": SalaryBand(22, 50),
    "sde 2": SalaryBand(25, 55),
    "senior software engineer": SalaryBand(30, 65),
    "staff engineer": SalaryBand(55, 95),
    "engineering manager": SalaryBand(50, 100),
    "default": SalaryBand(20, 45),
}

BENCHMARK_SEED = [
    ("frontend engineer", 0, 3, 8, 18),
    ("frontend engineer", 3, 6, 16, 32),
    ("frontend engineer", 6, 9, 30, 48),
    ("backend engineer", 0, 3, 10, 20),
    ("backend engineer", 3, 6, 18, 36),
    ("backend engineer", 6, 9, 34, 52),
    ("full stack engineer", 0, 3, 10, 22),
    ("full stack engineer", 3, 6, 20, 40),
    ("full stack engineer", 6, 9, 36, 58),
    ("senior software engineer", 4, 7, 30, 60),
    ("senior software engineer", 7, 10, 45, 72),
    ("staff engineer", 7, 10, 55, 95),
    ("engineering manager", 7, 10, 50, 100),
    ("default", 0, 4, 10, 25),
    ("default", 4, 7, 20, 40),
    ("default", 7, 12, 35, 65),
]


SKILL_KEYWORDS = {
    "frontend": [
        "react",
        "next.js",
        "typescript",
        "javascript",
        "css",
        "redux",
    ],
    "backend": [
        "python",
        "java",
        "node",
        "go",
        "microservices",
        "api",
        "database",
    ],
    "system_design": [
        "distributed systems",
        "scalability",
        "caching",
        "queue",
        "event-driven",
        "kafka",
        "load balancer",
    ],
    "leadership": [
        "mentored",
        "led",
        "managed",
        "hired",
        "roadmap",
        "cross-functional",
    ],
}


class SalaryRealityCheck(BaseModel):
    status: str = Field(description="underpaid / fairly_paid / overpaid")
    current_lpa: float
    market_band_lpa: dict[str, float]
    estimated_gap_lpa: dict[str, float]
    benchmark_message: str


class CareerRiskSignal(BaseModel):
    severity: str = Field(description="low / medium / high")
    signal: str
    reason: str
    mitigation: str


class ActionPlanItem(BaseModel):
    category: str = Field(description="learn / build / apply")
    title: str
    details: list[str]
    expected_impact: str


class TimelinePrediction(BaseModel):
    target_comp_lpa: float
    timeline_months: int
    confidence: str
    assumptions: list[str]
    summary: str


class TrackerItem(BaseModel):
    id: int
    title: str
    category: str
    week: int
    status: str
    source_gap: str
    created_at: str
    completed_at: Optional[str]


class TrackerItemsResponse(BaseModel):
    completion_percent: int
    items: list[TrackerItem]


class TrackerStatusUpdate(BaseModel):
    status: str = Field(description="todo / in_progress / done")


class ChecklistItem(BaseModel):
    id: int
    title: str
    day: int
    category: str
    status: str
    created_at: str
    completed_at: Optional[str]


class ChecklistResponse(BaseModel):
    completion_percent: int
    items: list[ChecklistItem]


class ChecklistStatusUpdate(BaseModel):
    status: str = Field(description="todo / in_progress / done")


class CareerGPSResponse(BaseModel):
    current_role: str
    target_path: str
    gap_analysis: list[str]
    success_probability_percent: int
    time_to_achieve_months: int
    confidence: str
    factors: dict[str, float]
    explainable_probability: list[dict[str, object]]
    probability_lift_to_40: list[dict[str, object]]
    next_30_day_action_engine: list[dict[str, object]]
    simulation_used: dict[str, object]
    summary: str
    key_insight: Optional[str] = None
    claude_enhanced: bool = False


class AuditResponse(BaseModel):
    inferred_current_role: str
    inferred_years_experience: float
    requested_target_role: Optional[str]
    inferred_skills: dict[str, list[str]]
    readiness_score: int
    score_breakdown: dict[str, int]
    score_explanation: list[str]
    priority_gaps: list[str]
    action_plan_track: str
    action_plan_rationale: str
    salary_reality_check: SalaryRealityCheck
    career_risk_signals: list[CareerRiskSignal]
    action_plan: list[ActionPlanItem]
    timeline_prediction: TimelinePrediction
    llm_enhanced: bool


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS salary_benchmarks (
                role TEXT NOT NULL,
                exp_min REAL NOT NULL,
                exp_max REAL NOT NULL,
                min_lpa REAL NOT NULL,
                max_lpa REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                current_salary_lpa REAL NOT NULL,
                years_experience REAL NOT NULL,
                target_role TEXT,
                inferred_role TEXT NOT NULL,
                readiness_score INTEGER NOT NULL,
                underpaid_min REAL NOT NULL,
                underpaid_max REAL NOT NULL,
                timeline_months INTEGER NOT NULL,
                audit_payload TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracker_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                audit_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                week INTEGER NOT NULL,
                status TEXT NOT NULL,
                source_gap TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                completed_at TEXT,
                UNIQUE(audit_id, fingerprint)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checklist_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                audit_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                title TEXT NOT NULL,
                day INTEGER NOT NULL,
                category TEXT NOT NULL,
                status TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                completed_at TEXT,
                UNIQUE(audit_id, fingerprint)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS claude_gps_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                audit_id INTEGER,
                current_role TEXT NOT NULL,
                target_path TEXT NOT NULL,
                simulation_flags TEXT NOT NULL,
                input_context TEXT NOT NULL,
                claude_response TEXT NOT NULL,
                base_probability INTEGER NOT NULL,
                adjusted_probability INTEGER NOT NULL,
                base_timeline_months INTEGER NOT NULL,
                adjusted_timeline_months INTEGER NOT NULL,
                user_feedback TEXT,
                feedback_score INTEGER
            )
            """
        )

        existing = conn.execute("SELECT COUNT(*) AS count FROM salary_benchmarks").fetchone()
        if existing and existing["count"] == 0:
            conn.executemany(
                """
                INSERT INTO salary_benchmarks (role, exp_min, exp_max, min_lpa, max_lpa)
                VALUES (?, ?, ?, ?, ?)
                """,
                BENCHMARK_SEED,
            )

        columns = conn.execute("PRAGMA table_info(audit_runs)").fetchall()
        column_names = {row["name"] for row in columns}
        if "audit_payload" not in column_names:
            conn.execute("ALTER TABLE audit_runs ADD COLUMN audit_payload TEXT")

        # Migrate existing tracker_items and checklist_items tables to add audit_id
        tracker_columns = conn.execute("PRAGMA table_info(tracker_items)").fetchall()
        tracker_column_names = {row["name"] for row in tracker_columns}
        if "audit_id" not in tracker_column_names:
            # Create new table with audit_id
            conn.execute("""
                CREATE TABLE tracker_items_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    audit_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    week INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    source_gap TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    completed_at TEXT,
                    UNIQUE(audit_id, fingerprint)
                )
            """)
            # Get the latest audit_id or use 1 as default
            latest_audit = conn.execute("SELECT id FROM audit_runs ORDER BY id DESC LIMIT 1").fetchone()
            default_audit_id = latest_audit["id"] if latest_audit else 1
            # Copy data with default audit_id
            conn.execute(f"""
                INSERT INTO tracker_items_new (id, audit_id, created_at, title, category, week, status, source_gap, fingerprint, completed_at)
                SELECT id, {default_audit_id}, created_at, title, category, week, status, source_gap, fingerprint, completed_at
                FROM tracker_items
            """)
            conn.execute("DROP TABLE tracker_items")
            conn.execute("ALTER TABLE tracker_items_new RENAME TO tracker_items")

        checklist_columns = conn.execute("PRAGMA table_info(checklist_items)").fetchall()
        checklist_column_names = {row["name"] for row in checklist_columns}
        if "audit_id" not in checklist_column_names:
            # Create new table with audit_id
            conn.execute("""
                CREATE TABLE checklist_items_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    audit_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    title TEXT NOT NULL,
                    day INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    completed_at TEXT,
                    UNIQUE(audit_id, fingerprint)
                )
            """)
            # Get the latest audit_id or use 1 as default
            latest_audit = conn.execute("SELECT id FROM audit_runs ORDER BY id DESC LIMIT 1").fetchone()
            default_audit_id = latest_audit["id"] if latest_audit else 1
            # Copy data with default audit_id
            conn.execute(f"""
                INSERT INTO checklist_items_new (id, audit_id, created_at, title, day, category, status, fingerprint, completed_at)
                SELECT id, {default_audit_id}, created_at, title, day, category, status, fingerprint, completed_at
                FROM checklist_items
            """)
            conn.execute("DROP TABLE checklist_items")
            conn.execute("ALTER TABLE checklist_items_new RENAME TO checklist_items")

        conn.commit()


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def normalize_role(role: Optional[str]) -> str:
    if not role:
        return "default"
    role_key = role.strip().lower()
    alias_map = {
        "em": "engineering manager",
        "engineering mgr": "engineering manager",
        "eng manager": "engineering manager",
        "frontend developer": "frontend engineer",
        "backend developer": "backend engineer",
        "fullstack engineer": "full stack engineer",
        "fullstack developer": "full stack engineer",
        "sde2": "sde 2",
        "sde ii": "sde 2",
    }
    if role_key in alias_map:
        return alias_map[role_key]
    for known_role in ROLE_BANDS:
        if known_role in role_key:
            return known_role
    return "default"


def extract_text_from_upload(upload: UploadFile, raw: bytes) -> str:
    content_type = upload.content_type or ""
    filename = (upload.filename or "").lower()

    if "text" in content_type or filename.endswith(".txt"):
        return raw.decode("utf-8", errors="ignore")

    if "pdf" in content_type or filename.endswith(".pdf"):
        try:
            reader = PdfReader(BytesIO(raw))
            pages = [page.extract_text() or "" for page in reader.pages]
            parsed = "\n".join(pages).strip()
            if parsed:
                return parsed
        except Exception:
            return ""
        return ""

    if "word" in content_type or filename.endswith(".docx"):
        try:
            doc = Document(BytesIO(raw))
            parsed = "\n".join([paragraph.text for paragraph in doc.paragraphs]).strip()
            if parsed:
                return parsed
        except Exception:
            return ""
        return ""

    # For unknown types, best-effort text decode.
    return raw.decode("utf-8", errors="ignore")


def validate_resume_text(resume_text: str) -> tuple[bool, str]:
    words = re.findall(r"[a-zA-Z]{2,}", resume_text)
    if len(words) < 80:
        return False, "Resume text is too short or unreadable. Please upload a valid resume PDF/DOCX."

    code_punctuation_count = len(re.findall(r"[{};<>]", resume_text))
    alpha_count = len(re.findall(r"[a-zA-Z]", resume_text))
    if alpha_count > 0 and (code_punctuation_count / alpha_count) > 0.08:
        return False, "Uploaded file appears to be code or non-resume content. Please upload your actual resume."

    lower_text = resume_text.lower()
    section_hits = 0
    expected_sections = [
        "experience",
        "education",
        "skills",
        "project",
        "work",
        "summary",
        "responsibility",
    ]
    for section in expected_sections:
        if section in lower_text:
            section_hits += 1

    year_matches = re.findall(r"(19|20)\d{2}", lower_text)
    contact_signals = 1 if ("@" in resume_text or "linkedin" in lower_text) else 0

    has_resume_timeline = len(year_matches) >= 2
    has_resume_identity = contact_signals > 0
    if section_hits < 3 or (not has_resume_timeline and not has_resume_identity):
        return False, "Uploaded file does not look like a resume. Please upload your actual resume."

    return True, ""


def infer_skills(resume_text: str) -> dict[str, list[str]]:
    text = resume_text.lower()
    found: dict[str, list[str]] = {}
    for bucket, keywords in SKILL_KEYWORDS.items():
        found[bucket] = [kw for kw in keywords if kw in text]
    return found


def infer_current_role(skills: dict[str, list[str]], experience_years: float) -> str:
    front_score = len(skills["frontend"])
    back_score = len(skills["backend"])
    design_score = len(skills["system_design"])
    leadership_score = len(skills["leadership"])

    if leadership_score >= 2 and experience_years >= 8:
        return "engineering manager"
    if design_score >= 3 and experience_years >= 7:
        return "staff engineer"
    if front_score >= 3 and back_score >= 3:
        return "full stack engineer"
    if front_score > back_score:
        return "frontend engineer"
    if back_score > 0:
        return "backend engineer"
    if experience_years >= 6:
        return "senior software engineer"
    return "sde 2"


def infer_years_experience(resume_text: str, fallback_years: Optional[float]) -> float:
    if fallback_years is not None:
        return fallback_years

    lower_text = resume_text.lower()
    detected: list[float] = []

    range_matches = re.findall(r"(\d+(?:\.\d+)?)\s*[-to]+\s*(\d+(?:\.\d+)?)\s*(?:\+?\s*)?(?:years|yrs)", lower_text)
    for start, end in range_matches:
        try:
            detected.append(max(float(start), float(end)))
        except ValueError:
            continue

    single_matches = re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs)", lower_text)
    for value in single_matches:
        try:
            detected.append(float(value))
        except ValueError:
            continue

    if not detected:
        return 3.0

    return round(max(0.0, min(max(detected), 25.0)), 1)


def get_benchmark_band(role_for_benchmark: str, years_experience: float) -> SalaryBand:
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT min_lpa, max_lpa
            FROM salary_benchmarks
            WHERE role = ?
              AND ? >= exp_min
              AND ? < exp_max
            LIMIT 1
            """,
            (role_for_benchmark, years_experience, years_experience),
        ).fetchone()

        if not row:
            row = conn.execute(
                """
                SELECT min_lpa, max_lpa
                FROM salary_benchmarks
                WHERE role = ?
                ORDER BY exp_max DESC
                LIMIT 1
                """,
                (role_for_benchmark,),
            ).fetchone()

        if not row:
            default_row = conn.execute(
                """
                SELECT min_lpa, max_lpa
                FROM salary_benchmarks
                WHERE role = 'default'
                  AND ? >= exp_min
                  AND ? < exp_max
                LIMIT 1
                """,
                (years_experience, years_experience),
            ).fetchone()
            if not default_row:
                return ROLE_BANDS["default"]
            return SalaryBand(default_row["min_lpa"], default_row["max_lpa"])

        return SalaryBand(row["min_lpa"], row["max_lpa"])


def salary_reality_check(
    current_lpa: float,
    role_for_benchmark: str,
    years_experience: float,
) -> SalaryRealityCheck:
    band = get_benchmark_band(role_for_benchmark, years_experience)
    min_gap = round(band.min_lpa - current_lpa, 1)
    max_gap = round(band.max_lpa - current_lpa, 1)

    if current_lpa < band.min_lpa:
        status = "underpaid"
        message = f"You are likely underpaid by about {abs(min_gap):.1f}-{abs(max_gap):.1f} LPA."
    elif current_lpa > band.max_lpa:
        status = "overpaid"
        message = "You are above benchmark for this role, focus on role expansion."
    else:
        status = "fairly_paid"
        message = "You are within the market band; upside comes from role upgrade."

    return SalaryRealityCheck(
        status=status,
        current_lpa=current_lpa,
        market_band_lpa={"min": band.min_lpa, "max": band.max_lpa},
        estimated_gap_lpa={"min": min_gap, "max": max_gap},
        benchmark_message=message,
    )


def build_priority_gaps(
    skills: dict[str, list[str]],
    experience_years: float,
    target_role: Optional[str],
) -> list[str]:
    gaps: list[str] = []
    target_lower = (target_role or "").lower()

    if len(skills["system_design"]) < 2:
        gaps.append("System design depth is below senior-role benchmark.")
    if len(skills["backend"]) < 2:
        gaps.append("Backend evidence is thin; profile appears too implementation-layer heavy.")
    if len(skills["leadership"]) == 0 and experience_years >= 6:
        gaps.append("Leadership/ownership bullets are missing for your tenure.")
    if "manager" in target_lower and len(skills["leadership"]) < 2:
        gaps.append("EM target selected, but people-management and hiring signals are limited.")
    if not gaps:
        gaps.append("No critical capability gap detected; focus on interview execution quality.")

    return gaps[:3]


def calculate_readiness_score(
    skills: dict[str, list[str]],
    risks: list[CareerRiskSignal],
    years_experience: float,
    target_role: Optional[str],
) -> tuple[int, dict[str, int], list[str]]:
    frontend_points = min(30, len(skills["frontend"]) * 5)
    backend_points = min(30, len(skills["backend"]) * 6)
    system_design_points = min(20, len(skills["system_design"]) * 6)
    leadership_points = min(20, len(skills["leadership"]) * 6)
    skill_points = frontend_points + backend_points + system_design_points + leadership_points

    risk_penalty = sum(12 if r.severity == "high" else 7 if r.severity == "medium" else 3 for r in risks)
    exp_bonus = 8 if years_experience >= 7 else 4 if years_experience >= 4 else 0
    manager_penalty = 8 if "manager" in (target_role or "").lower() and len(skills["leadership"]) < 2 else 0

    score = skill_points + exp_bonus - risk_penalty - manager_penalty
    bounded_score = max(25, min(92, int(score)))
    breakdown = {
        "frontend_depth": frontend_points,
        "backend_depth": backend_points,
        "system_design_depth": system_design_points,
        "leadership_signal": leadership_points,
        "experience_bonus": exp_bonus,
        "risk_penalty": -risk_penalty,
        "manager_readiness_penalty": -manager_penalty,
    }
    explanation = [
        f"Skill depth contribution: {skill_points} points from frontend/backend/system design/leadership signals.",
        f"Experience bonus: +{exp_bonus} based on inferred tenure of {years_experience} years.",
        f"Risk penalties: -{risk_penalty} from detected career risk severity.",
    ]
    if manager_penalty > 0:
        explanation.append(
            f"Manager-track penalty: -{manager_penalty} due to limited people-management evidence."
        )
    explanation.append(f"Final readiness score (bounded): {bounded_score}/100.")
    return bounded_score, breakdown, explanation


def build_risk_signals(
    skills: dict[str, list[str]],
    experience_years: float,
    inferred_role: str,
    target_role: Optional[str],
) -> list[CareerRiskSignal]:
    signals: list[CareerRiskSignal] = []
    target_lower = (target_role or "").lower()

    if len(skills["frontend"]) >= 3 and len(skills["backend"]) <= 1:
        signals.append(
            CareerRiskSignal(
                severity="high",
                signal="Frontend-concentrated profile",
                reason="Most profile signals are frontend; backend breadth is limited.",
                mitigation=(
                    "Ship one backend-heavy project with auth, database tuning, "
                    "caching, and API performance metrics."
                ),
            )
        )

    if len(skills["system_design"]) < 2 and (
        "manager" in target_lower or inferred_role in {"staff engineer", "engineering manager"}
    ):
        signals.append(
            CareerRiskSignal(
                severity="high",
                signal="Low system design evidence",
                reason="Resume lacks strong architecture keywords and scale examples.",
                mitigation=(
                    "Add two design case studies: high-QPS API and asynchronous event pipeline "
                    "with trade-off documentation."
                ),
            )
        )

    if len(skills["leadership"]) == 0 and experience_years >= 7:
        signals.append(
            CareerRiskSignal(
                severity="medium",
                signal="Limited leadership signal",
                reason="No hiring/mentoring/ownership indicators despite senior tenure.",
                mitigation="Lead one cross-team initiative and document business impact numbers.",
            )
        )

    if not signals:
        signals.append(
            CareerRiskSignal(
                severity="low",
                signal="No critical blockers detected",
                reason="Profile has baseline breadth for current trajectory.",
                mitigation="Continue strengthening measurable impact and interview readiness.",
            )
        )

    return signals


def build_action_plan(
    skills: dict[str, list[str]],
    inferred_role: str,
    target_role: Optional[str],
    priority_gaps: list[str],
    experience_years: float,
) -> tuple[list[ActionPlanItem], str, str]:
    def unique_lines(lines: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for line in lines:
            key = re.sub(r"\W+", "", line.lower())
            if key and key not in seen:
                seen.add(key)
                result.append(line)
        return result

    target = (target_role or inferred_role).lower()
    frontend_score = len(skills["frontend"])
    backend_score = len(skills["backend"])
    system_score = len(skills["system_design"])
    leadership_score = len(skills["leadership"])

    if "manager" in target:
        track = "management"
        rationale = "Selected management track because your target role indicates people leadership expectations."
    elif "staff" in target or "principal" in target or (system_score >= 3 and experience_years >= 7):
        track = "architecture"
        rationale = "Selected architecture track due to seniority/system-design trajectory toward staff-level scope."
    elif frontend_score >= 3 and backend_score <= 1:
        track = "frontend_to_fullstack"
        rationale = "Selected frontend-to-fullstack track because frontend signals dominate and backend depth is limited."
    elif backend_score >= 3 and frontend_score <= 1:
        track = "backend_to_senior"
        rationale = "Selected backend-to-senior track because backend depth is strong and role progression needs advanced system ownership."
    else:
        track = "balanced_fullstack"
        rationale = "Selected balanced full-stack track because your profile shows mixed capability signals without a single dominant gap."

    learn_map = {
        "management": (
            "Develop engineering leadership toolkit",
            [
                "Roadmap prioritization using impact vs effort and headcount constraints.",
                "1:1 coaching framework, performance calibration, and feedback loops.",
                "Execution rituals: sprint health metrics, risk burndown, and stakeholder updates.",
            ],
            "Builds EM interview signal beyond pure coding strength.",
        ),
        "architecture": (
            "Master senior architecture decision patterns",
            [
                "Data partitioning and multi-tenant isolation strategies.",
                "Event-driven consistency patterns and failure recovery design.",
                "Latency-budgeting and capacity planning with SLO-based trade-offs.",
            ],
            "Improves credibility for Staff/Principal design interviews.",
        ),
        "frontend_to_fullstack": (
            "Expand from frontend specialist to full-stack owner",
            [
                "API design fundamentals: versioning, pagination, and idempotency.",
                "Database modeling for transactional and analytics workloads.",
                "Production backend debugging: tracing, retries, and circuit breakers.",
            ],
            "Adds backend depth needed for senior product engineering roles.",
        ),
        "backend_to_senior": (
            "Strengthen backend profile for top-tier senior roles",
            [
                "Advanced caching hierarchy and cache-invalidation patterns.",
                "Concurrency control and message-driven processing reliability.",
                "System design storytelling with metrics and architecture trade-offs.",
            ],
            "Raises conversion for high-comp backend interview loops.",
        ),
        "balanced_fullstack": (
            "Sharpen full-stack execution for role elevation",
            [
                "End-to-end performance optimization from UI render to DB query path.",
                "Security fundamentals: authZ boundaries, token design, and audit trails.",
                "System design communication using constraints and measurable outcomes.",
            ],
            "Helps move from execution-heavy profile to ownership-heavy profile.",
        ),
    }

    build_map = {
        "management": "Internal developer productivity platform with team-level engineering metrics",
        "architecture": "Distributed event processing system with reliability and observability dashboards",
        "frontend_to_fullstack": "SaaS workflow product with React frontend, Python APIs, and PostgreSQL",
        "backend_to_senior": "High-throughput backend service with async jobs, caching, and rate limiting",
        "balanced_fullstack": "Customer analytics platform with full-stack ownership and production telemetry",
    }

    apply_map = {
        "management": "mid-large engineering orgs hiring EMs",
        "architecture": "platform-focused scale-ups and late-stage product companies",
        "frontend_to_fullstack": "product companies hiring full-stack engineers",
        "backend_to_senior": "backend-heavy teams in fintech, SaaS, and infra startups",
        "balanced_fullstack": "global SaaS companies and strong India product orgs",
    }

    learn_title, learn_details, learn_impact = learn_map[track]
    first_gap = priority_gaps[0] if priority_gaps else "Demonstrate clear measurable ownership."

    plan = [
        ActionPlanItem(
            category="learn",
            title=learn_title,
            details=unique_lines(learn_details),
            expected_impact=learn_impact,
        ),
        ActionPlanItem(
            category="build",
            title=f"Build one flagship project: {build_map[track]}",
            details=unique_lines(
                [
                    "Define architecture options and explicitly document why one design was chosen.",
                    "Ship production-style quality: tests, observability, and deployment notes.",
                    "Publish measurable outcomes (latency, reliability, cost, or conversion metrics).",
                    f"Design this project to explicitly close gap: {first_gap}",
                ]
            ),
            expected_impact="Creates concrete proof of ownership, execution, and business impact.",
        ),
        ActionPlanItem(
            category="apply",
            title=f"Target {apply_map[track]}",
            details=unique_lines(
                [
                    "Build a 40-company list segmented by stretch, realistic, and safe opportunities.",
                    "Apply to 10-15 roles/week with role-specific impact bullets and referrals.",
                    "Run 3 focused mocks/week aligned to your track (coding/design/leadership mix).",
                    "Update resume bullets weekly with quantified outcomes from your flagship project.",
                ]
            ),
            expected_impact="Increases interview pipeline quality and improves offer conversion.",
        ),
    ]

    # Leadership-light senior profiles get one additional, personalized nudge.
    if leadership_score == 0 and experience_years >= 6 and track != "management":
        plan[0].details = unique_lines(
            plan[0].details
            + ["Practice ownership narratives: scope, trade-off decisions, and cross-team influence."]
        )

    if priority_gaps:
        rationale = f"{rationale} Highest-priority gap: {priority_gaps[0]}"

    return plan, track, rationale


def timeline_prediction(
    current_lpa: float,
    benchmark_band: SalaryBand,
    risks: list[CareerRiskSignal],
    experience_years: float,
) -> TimelinePrediction:
    risk_weight = {"low": 1, "medium": 2, "high": 3}
    avg_risk = mean([risk_weight[r.severity] for r in risks])

    target_comp = round(benchmark_band.max_lpa * 0.9, 1)
    # Keep target comp realistic and forward-looking.
    if target_comp <= current_lpa:
        target_comp = round(current_lpa * 1.12, 1)
    compensation_jump = max(0.0, target_comp - current_lpa)

    base_months = 6 if compensation_jump <= 10 else 9 if compensation_jump <= 20 else 12
    exp_penalty = 2 if experience_years < 3 else 0
    risk_penalty = int(avg_risk)
    months = base_months + exp_penalty + risk_penalty

    if months <= 9:
        confidence = "high"
    elif months <= 14:
        confidence = "medium"
    else:
        confidence = "low"

    assumptions = [
        "8-10 focused hours/week on upskilling and interview prep.",
        "Consistent applications and referral outreach every week.",
        "At least one high-quality portfolio project shipped in 60 days.",
    ]

    summary = (
        f"Based on your current profile, a move to about {target_comp} LPA in {months} months "
        f"is plausible with {confidence} confidence if execution stays consistent."
    )

    return TimelinePrediction(
        target_comp_lpa=target_comp,
        timeline_months=months,
        confidence=confidence,
        assumptions=assumptions,
        summary=summary,
    )


def sanitize_text(value: str) -> str:
    value = value.strip()
    value = re.sub(r"\s+", " ", value)
    return value


def _extract_json_object(text: str) -> Optional[dict[str, Any]]:
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = text[start : end + 1]
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def audit_with_llm(
    resume_text: str,
    current_salary_lpa: float,
    years_experience: Optional[float],
    target_role: Optional[str],
) -> Optional[dict[str, Any]]:
    provider = LLMFactory.get_provider()
    if not provider:
        return None
    
    target_context = f"Target role: {target_role}" if target_role else "No specific target role provided"
    exp_context = f"Stated experience: {years_experience} years" if years_experience else "Experience to be inferred from resume"
    
    prompt = (
        "You are an expert career auditor for software engineers in the Indian tech market. "
        "Analyze the resume and provide a comprehensive career audit. Return ONLY valid JSON.\n\n"
        "Task: Analyze this engineer's profile and provide actionable career guidance.\n\n"
        "Rules:\n"
        "- CAREFULLY infer years of experience by analyzing:\n"
        "  * Work history dates and duration of each role\n"
        "  * Total career span from first job to present\n"
        "  * Education graduation year if mentioned\n"
        "  * Explicit experience statements (e.g., '8 years of experience')\n"
        "  * If unclear, estimate conservatively based on role progression\n"
        "- Infer current role from most recent position title\n"
        "- Identify skill strengths across frontend, backend, system design, and leadership\n"
        "- Assess readiness score (25-92) based on skill depth, experience, and target fit\n"
        "- Identify 3-4 priority gaps blocking career growth\n"
        "- Flag 2-3 career risk signals (low/medium/high severity)\n"
        "- Provide 3 action items (learn/build/apply categories)\n"
        "- Generate 8-10 weekly execution tracker tasks (weeks 1-4) with specific, actionable items\n"
        "- Generate 5 milestone checklist items for days 3, 7, 14, 21, 30\n"
        "- Estimate realistic timeline to target role (4-18 months)\n"
        "- Be specific and concrete, avoid generic advice\n"
        "- Consider Indian tech market context (compensation, hiring patterns)\n\n"
        "JSON shape:\n"
        "{\n"
        '  "inferred_current_role": "specific role title",\n'
        '  "inferred_years_experience": 3.5,\n'
        '  "inferred_skills": {\n'
        '    "frontend": ["react", "typescript", ...],\n'
        '    "backend": ["python", "api", ...],\n'
        '    "system_design": ["scalability", ...],\n'
        '    "leadership": ["mentored", ...]\n'
        '  },\n'
        '  "readiness_score": 65,\n'
        '  "readiness_explanation": "Why this score - be specific",\n'
        '  "priority_gaps": ["gap 1", "gap 2", "gap 3"],\n'
        '  "career_risk_signals": [\n'
        '    {"severity": "high|medium|low", "signal": "...", "reason": "...", "mitigation": "..."}\n'
        '  ],\n'
        '  "action_plan": [\n'
        '    {"category": "learn|build|apply", "title": "...", "details": ["..."], "expected_impact": "..."}\n'
        '  ],\n'
        '  "execution_tracker": [\n'
        '    {"title": "Specific task", "category": "learn|build|apply", "week": 1-4, "source_gap": "related gap"}\n'
        '  ],\n'
        '  "checklist_30day": [\n'
        '    {"title": "Day X milestone", "day": 3|7|14|21|30, "category": "learn|build|apply"}\n'
        '  ],\n'
        '  "timeline_months": 9,\n'
        '  "timeline_confidence": "high|medium|low",\n'
        '  "timeline_summary": "Realistic timeline explanation with conditions",\n'
        '  "action_plan_track": "management|architecture|frontend_to_fullstack|backend_to_senior|balanced_fullstack",\n'
        '  "action_plan_rationale": "Why this track was chosen"\n'
        "}\n\n"
        f"Context:\n"
        f"- Current salary: {current_salary_lpa} LPA\n"
        f"- {exp_context}\n"
        f"- {target_context}\n\n"
        f"Resume content (first 8000 chars):\n{resume_text[:8000]}"
    )

    try:
        llm_response = provider.generate(
            prompt=prompt,
            max_tokens=3000,
            temperature=0.25,
        )
        full_response = llm_response.content
        print(f"[DEBUG] {provider.get_provider_name()} audit response length: {len(full_response)} chars")
        llm_audit = extract_json_from_llm_response(full_response)
        if llm_audit:
            print(f"[DEBUG] LLM audit parsed successfully. Keys: {list(llm_audit.keys())}")
        else:
            print(f"[DEBUG] Failed to parse LLM response as JSON. First 500 chars: {full_response[:500]}")
        return llm_audit
    except Exception as e:
        print(f"[ERROR] LLM audit error: {e}")
        return None


def save_audit_run(
    current_salary_lpa: float,
    years_experience: float,
    target_role: Optional[str],
    inferred_role: str,
    readiness_score: int,
    underpaid_min: float,
    underpaid_max: float,
    timeline_months: int,
    audit_payload: Optional[str] = None,
) -> int:
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO audit_runs (
                created_at,
                current_salary_lpa,
                years_experience,
                target_role,
                inferred_role,
                readiness_score,
                underpaid_min,
                underpaid_max,
                timeline_months,
                audit_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                current_salary_lpa,
                years_experience,
                target_role,
                inferred_role,
                readiness_score,
                underpaid_min,
                underpaid_max,
                timeline_months,
                audit_payload,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def _fingerprint(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def build_tracker_items(action_plan: list[ActionPlanItem], priority_gaps: list[str]) -> list[dict[str, object]]:
    if not action_plan:
        return []

    top_gap = priority_gaps[0] if priority_gaps else "General execution consistency"
    category_weight = {"learn": 1, "build": 2, "apply": 3}
    tasks: list[dict[str, object]] = []

    for item in action_plan:
        details = item.details[:3]
        for idx, detail in enumerate(details):
            week = idx + 1 if item.category != "build" else idx + 2
            tasks.append(
                {
                    "title": f"{item.category.title()}: {detail}",
                    "category": item.category,
                    "week": max(1, min(4, week)),
                    "source_gap": top_gap,
                    "priority": category_weight.get(item.category, 4),
                }
            )

    unique: dict[str, dict[str, object]] = {}
    for task in tasks:
        key = _fingerprint(f"{task['category']}::{task['title']}")
        if key not in unique:
            unique[key] = task

    return list(unique.values())


def upsert_tracker_items(
    audit_id: int, 
    action_plan: list[ActionPlanItem], 
    priority_gaps: list[str],
    llm_tracker_items: Optional[list[dict[str, object]]] = None
) -> None:
    # Use LLM-generated items if available, otherwise fall back to rule-based
    if llm_tracker_items and len(llm_tracker_items) > 0:
        tracker_items = llm_tracker_items
        print(f"[INFO] Using {len(tracker_items)} LLM-generated tracker items")
    else:
        tracker_items = build_tracker_items(action_plan, priority_gaps)
        print(f"[INFO] Using {len(tracker_items)} rule-based tracker items")
    
    if not tracker_items:
        return

    with get_db_connection() as conn:
        for item in tracker_items:
            fingerprint = _fingerprint(f"{item['category']}::{item['title']}")
            conn.execute(
                """
                INSERT INTO tracker_items (
                    audit_id, created_at, title, category, week, status, source_gap, fingerprint
                )
                VALUES (?, ?, ?, ?, ?, 'todo', ?, ?)
                ON CONFLICT(audit_id, fingerprint) DO UPDATE SET
                    week = excluded.week,
                    source_gap = excluded.source_gap
                """,
                (
                    audit_id,
                    datetime.now(timezone.utc).isoformat(),
                    item["title"],
                    item["category"],
                    item["week"],
                    item["source_gap"],
                    fingerprint,
                ),
            )
        conn.commit()


def fetch_tracker_items(audit_id: Optional[int] = None) -> TrackerItemsResponse:
    with get_db_connection() as conn:
        if audit_id is None:
            # Get the latest audit_id
            latest_audit = conn.execute("SELECT id FROM audit_runs ORDER BY id DESC LIMIT 1").fetchone()
            if not latest_audit:
                return TrackerItemsResponse(completion_percent=0, items=[])
            audit_id = latest_audit["id"]
        
        rows = conn.execute(
            """
            SELECT id, title, category, week, status, source_gap, created_at, completed_at
            FROM tracker_items
            WHERE audit_id = ?
            ORDER BY
              CASE status
                WHEN 'in_progress' THEN 0
                WHEN 'todo' THEN 1
                WHEN 'done' THEN 2
                ELSE 3
              END,
              week ASC,
              id DESC
            """,
            (audit_id,)
        ).fetchall()

    items = [
        TrackerItem(
            id=row["id"],
            title=row["title"],
            category=row["category"],
            week=row["week"],
            status=row["status"],
            source_gap=row["source_gap"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )
        for row in rows
    ]
    if not items:
        return TrackerItemsResponse(completion_percent=0, items=[])

    done_count = len([item for item in items if item.status == "done"])
    completion_percent = int((done_count / len(items)) * 100)
    return TrackerItemsResponse(completion_percent=completion_percent, items=items)


def build_30_day_checklist(action_plan: list[ActionPlanItem]) -> list[dict[str, object]]:
    milestones = [3, 7, 14, 21, 30]
    collected: list[dict[str, object]] = []

    for item in action_plan:
        for detail in item.details[:2]:
            collected.append({"title": detail, "category": item.category})

    if not collected:
        return []

    checklist: list[dict[str, object]] = []
    for idx, item in enumerate(collected[:5]):
        checklist.append(
            {
                "title": f"Day {milestones[idx]}: {item['title']}",
                "day": milestones[idx],
                "category": item["category"],
            }
        )
    return checklist


def upsert_30_day_checklist(
    audit_id: int, 
    action_plan: list[ActionPlanItem],
    llm_checklist_items: Optional[list[dict[str, object]]] = None
) -> None:
    # Use LLM-generated items if available, otherwise fall back to rule-based
    if llm_checklist_items and len(llm_checklist_items) > 0:
        checklist_items = llm_checklist_items
        print(f"[INFO] Using {len(checklist_items)} LLM-generated checklist items")
    else:
        checklist_items = build_30_day_checklist(action_plan)
        print(f"[INFO] Using {len(checklist_items)} rule-based checklist items")
    
    if not checklist_items:
        return

    with get_db_connection() as conn:
        for item in checklist_items:
            fingerprint = _fingerprint(f"{item['day']}::{item['category']}::{item['title']}")
            conn.execute(
                """
                INSERT INTO checklist_items (
                    audit_id, created_at, title, day, category, status, fingerprint
                )
                VALUES (?, ?, ?, ?, ?, 'todo', ?)
                ON CONFLICT(audit_id, fingerprint) DO UPDATE SET
                    day = excluded.day,
                    category = excluded.category
                """,
                (
                    audit_id,
                    datetime.now(timezone.utc).isoformat(),
                    item["title"],
                    item["day"],
                    item["category"],
                    fingerprint,
                ),
            )
        conn.commit()


def fetch_30_day_checklist(audit_id: Optional[int] = None) -> ChecklistResponse:
    with get_db_connection() as conn:
        if audit_id is None:
            # Get the latest audit_id
            latest_audit = conn.execute("SELECT id FROM audit_runs ORDER BY id DESC LIMIT 1").fetchone()
            if not latest_audit:
                return ChecklistResponse(completion_percent=0, items=[])
            audit_id = latest_audit["id"]
        
        rows = conn.execute(
            """
            SELECT id, title, day, category, status, created_at, completed_at
            FROM checklist_items
            WHERE audit_id = ?
            ORDER BY day ASC, id DESC
            """,
            (audit_id,)
        ).fetchall()

    items = [
        ChecklistItem(
            id=row["id"],
            title=row["title"],
            day=row["day"],
            category=row["category"],
            status=row["status"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )
        for row in rows
    ]
    if not items:
        return ChecklistResponse(completion_percent=0, items=[])

    done_count = len([item for item in items if item.status == "done"])
    completion_percent = int((done_count / len(items)) * 100)
    return ChecklistResponse(completion_percent=completion_percent, items=items)


def get_latest_audit_payload() -> Optional[dict[str, Any]]:
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT audit_payload
            FROM audit_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    if not row or not row["audit_payload"]:
        return None

    try:
        return json.loads(row["audit_payload"])
    except json.JSONDecodeError:
        return None


def _normalize_target_path(value: Optional[str]) -> str:
    target = (value or "").strip().lower()
    if target in {"staff", "staff engineer"}:
        return "staff engineer"
    if target in {"em", "engineering manager", "manager"}:
        return "engineering manager"
    if target in {"faang", "faang sde", "faang engineer"}:
        return "faang engineer"
    if target:
        return target
    return "staff engineer"


def save_claude_gps_interaction(
    audit_id: Optional[int],
    current_role: str,
    target_path: str,
    simulation_flags: dict[str, bool],
    input_context: dict[str, Any],
    claude_response: dict[str, Any],
    base_probability: int,
    adjusted_probability: int,
    base_timeline_months: int,
    adjusted_timeline_months: int,
) -> int:
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO claude_gps_interactions (
                created_at,
                audit_id,
                current_role,
                target_path,
                simulation_flags,
                input_context,
                claude_response,
                base_probability,
                adjusted_probability,
                base_timeline_months,
                adjusted_timeline_months
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                audit_id,
                current_role,
                target_path,
                json.dumps(simulation_flags),
                json.dumps(input_context),
                json.dumps(claude_response),
                base_probability,
                adjusted_probability,
                base_timeline_months,
                adjusted_timeline_months,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def enhance_career_gps_with_llm(
    current_role: str,
    target_path: str,
    inferred_skills: dict[str, list[str]],
    experience_years: float,
    priority_gaps: list[str],
    risks: list[dict[str, Any]],
    simulation_flags: dict[str, bool],
    base_probability: int,
    base_timeline_months: int,
    audit_id: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    provider = LLMFactory.get_provider()
    if not provider:
        return None
    
    simulation_context = []
    if simulation_flags.get("simulate_backend_shift"):
        simulation_context.append("Assuming candidate shifts to backend-heavy ownership")
    if simulation_flags.get("simulate_cross_team_leadership"):
        simulation_context.append("Assuming candidate leads cross-team initiatives")
    if simulation_flags.get("simulate_faang_prep"):
        simulation_context.append("Assuming candidate runs focused FAANG interview prep")
    
    simulation_note = f"Simulation context: {', '.join(simulation_context)}" if simulation_context else "No simulation applied (baseline trajectory)"
    
    prompt_payload = {
        "current_role": current_role,
        "target_path": target_path,
        "experience_years": experience_years,
        "skills": inferred_skills,
        "priority_gaps": priority_gaps,
        "risks": risks,
        "base_probability": base_probability,
        "base_timeline_months": base_timeline_months,
        "simulation_note": simulation_note,
    }
    
    prompt = (
        "You are a senior career strategist analyzing a software engineer's trajectory. Return ONLY valid JSON.\n\n"
        "Task: Provide personalized, actionable career guidance based on the profile and simulation context.\n\n"
        "Rules:\n"
        "- Be specific and concrete, not generic\n"
        "- Consider the simulation context when making recommendations\n"
        "- Gap analysis should reflect what's blocking the target path\n"
        "- Actions should be achievable within stated timeframes\n"
        "- Probability adjustments should be realistic (+/- 5-15%)\n"
        "- Timeline adjustments should be realistic (+/- 1-3 months)\n"
        "- If simulation is active, explain how it changes the trajectory\n\n"
        "JSON shape:\n"
        "{\n"
        '  "gap_analysis": ["specific gap 1", "specific gap 2", "..."],\n'
        '  "probability_adjustment_percent": -10 to +15,\n'
        '  "timeline_adjustment_months": -3 to +3,\n'
        '  "probability_lift_actions": [\n'
        '    {"action": "concrete action", "expected_lift_percent": 5-15, "reasoning": "why this helps"}\n'
        '  ],\n'
        '  "next_30_day_actions": [\n'
        '    {"action": "specific 30-day action", "expected_lift_percent": 3-8, "window_days": 14-30, "reasoning": "impact explanation"}\n'
        '  ],\n'
        '  "trajectory_summary": "2-3 sentence personalized summary with simulation context if applicable",\n'
        '  "key_insight": "One critical insight about their trajectory"\n'
        "}\n\n"
        f"Profile context:\n{json.dumps(prompt_payload, indent=2)}"
    )

    try:
        llm_response = provider.generate(
            prompt=prompt,
            max_tokens=2000,
            temperature=0.3,
        )
        full_response = llm_response.content
        print(f"[DEBUG] {provider.get_provider_name()} GPS enhancement response length: {len(full_response)} chars")
        enhanced = extract_json_from_llm_response(full_response)
        
        if enhanced:
            print(f"[DEBUG] LLM GPS parsed successfully. Adjustment: {enhanced.get('probability_adjustment_percent')}%")
        else:
            print(f"[DEBUG] Failed to parse GPS response. First 500 chars: {full_response[:500]}")
        
        # Save interaction for fine-tuning
        if enhanced:
            adjusted_prob = base_probability + int(enhanced.get("probability_adjustment_percent", 0))
            adjusted_timeline = base_timeline_months + int(enhanced.get("timeline_adjustment_months", 0))
            save_claude_gps_interaction(
                audit_id=audit_id,
                current_role=current_role,
                target_path=target_path,
                simulation_flags=simulation_flags,
                input_context=prompt_payload,
                claude_response=enhanced,
                base_probability=base_probability,
                adjusted_probability=adjusted_prob,
                base_timeline_months=base_timeline_months,
                adjusted_timeline_months=adjusted_timeline,
            )
        
        return enhanced
    except Exception:
        return None


def _build_target_gaps(
    target_path: str, inferred_skills: dict[str, list[str]], experience_years: float, priority_gaps: list[str]
) -> list[str]:
    gaps: list[str] = []
    backend_depth = len(inferred_skills.get("backend", []))
    design_depth = len(inferred_skills.get("system_design", []))
    leadership_depth = len(inferred_skills.get("leadership", []))

    if target_path == "staff engineer":
        if design_depth < 3:
            gaps.append("System design depth is below typical Staff expectations.")
        if backend_depth < 2:
            gaps.append("Backend architecture ownership signals are limited for Staff path.")
        if experience_years < 7:
            gaps.append("Typical Staff transitions become easier with 7+ years of scope evidence.")
    elif target_path == "engineering manager":
        if leadership_depth < 2:
            gaps.append("People leadership signals (hiring/mentoring/team ownership) are limited.")
        if design_depth < 2:
            gaps.append("Technical strategy depth should be stronger for EM interviews.")
        if experience_years < 6:
            gaps.append("EM hiring bar usually expects broad delivery ownership over multiple cycles.")
    elif target_path == "faang engineer":
        if design_depth < 2:
            gaps.append("System design readiness is below FAANG loop expectations.")
        if backend_depth < 2 and len(inferred_skills.get("frontend", [])) > 2:
            gaps.append("Profile looks frontend-heavy; FAANG loops expect stronger cross-stack depth.")
        gaps.append("Interview consistency needed for DSA + design + behavioral in one loop.")

    for gap in priority_gaps:
        if gap not in gaps:
            gaps.append(gap)

    if not gaps:
        gaps.append("No critical blockers detected; focus on execution consistency and interview cadence.")
    return gaps[:5]


def compute_career_gps(
    latest_audit: dict[str, Any],
    requested_target: Optional[str],
    simulate_backend_shift: bool = False,
    simulate_cross_team_leadership: bool = False,
    simulate_faang_prep: bool = False,
) -> CareerGPSResponse:
    target_path = _normalize_target_path(requested_target) or _normalize_target_path(
        latest_audit.get("requested_target_role")
    )
    current_role = latest_audit.get("inferred_current_role", "unknown")
    readiness = int(latest_audit.get("readiness_score", 25))
    base_timeline = int(latest_audit.get("timeline_prediction", {}).get("timeline_months", 12))
    inferred_skills = latest_audit.get("inferred_skills", {})
    experience_years = float(latest_audit.get("inferred_years_experience", 3.0))
    priority_gaps = latest_audit.get("priority_gaps", [])
    risks = latest_audit.get("career_risk_signals", [])

    # Scenario simulator changes the effective profile, not just probability math.
    effective_skills = {
        "frontend": list(inferred_skills.get("frontend", [])),
        "backend": list(inferred_skills.get("backend", [])),
        "system_design": list(inferred_skills.get("system_design", [])),
        "leadership": list(inferred_skills.get("leadership", [])),
    }
    effective_experience_years = experience_years
    effective_priority_gaps = list(priority_gaps)
    scenario_notes: list[str] = []

    if simulate_backend_shift:
        effective_skills["backend"].extend(["distributed systems", "api design"])
        effective_skills["system_design"].append("scalability")
        scenario_notes.append("Backend-heavy ownership simulated")
    if simulate_cross_team_leadership:
        effective_skills["leadership"].extend(["mentored", "roadmap"])
        effective_experience_years = max(effective_experience_years, experience_years + 0.8)
        scenario_notes.append("Cross-team leadership simulated")
    if simulate_faang_prep:
        effective_skills["system_design"].extend(["load balancer", "caching"])
        scenario_notes.append("FAANG prep simulated")

    if scenario_notes:
        filtered_gaps = []
        for gap in effective_priority_gaps:
            lower_gap = gap.lower()
            if simulate_backend_shift and ("backend" in lower_gap or "implementation-layer" in lower_gap):
                continue
            if simulate_cross_team_leadership and ("leadership" in lower_gap or "ownership" in lower_gap or "people-management" in lower_gap):
                continue
            if simulate_faang_prep and ("system design" in lower_gap or "interview" in lower_gap):
                continue
            filtered_gaps.append(gap)
        effective_priority_gaps = filtered_gaps
        
        # Add simulation-specific gaps
        if simulate_backend_shift:
            effective_priority_gaps.insert(0, "Focus on production reliability and observability for backend services")
        if simulate_cross_team_leadership:
            effective_priority_gaps.insert(0, "Document cross-team influence and measurable business outcomes")
        if simulate_faang_prep:
            effective_priority_gaps.insert(0, "Strengthen DSA fundamentals and system design communication")

    tracker_completion = fetch_tracker_items(audit_id=None).completion_percent
    checklist_completion = fetch_30_day_checklist(audit_id=None).completion_percent
    high_risk_count = len([risk for risk in risks if risk.get("severity") == "high"])
    medium_risk_count = len([risk for risk in risks if risk.get("severity") == "medium"])

    # Explainable Probability Engine: start from neutral baseline and apply named contributions.
    base_probability = 50
    readiness_impact = int((readiness - 50) * 0.5)
    design_depth = len(effective_skills.get("system_design", []))
    leadership_depth = len(effective_skills.get("leadership", []))
    backend_depth = len(effective_skills.get("backend", []))
    frontend_depth = len(effective_skills.get("frontend", []))
    design_impact = -12 if design_depth == 0 else -6 if design_depth == 1 else 4
    leadership_impact = -10 if leadership_depth == 0 and target_path == "engineering manager" else -5 if leadership_depth == 0 else 4
    scope_impact = -8 if effective_experience_years < 5 else -3 if effective_experience_years < 7 else 5
    coding_impact = 6 if (backend_depth + frontend_depth) >= 4 else 2
    risk_impact = -((high_risk_count * 8) + (medium_risk_count * 4))
    execution_impact = int((tracker_completion * 0.16) + (checklist_completion * 0.12))
    target_difficulty_impact = {"staff engineer": -8, "engineering manager": -12, "faang engineer": -14}.get(
        target_path, -8
    )

    simulation_impact = 0
    if simulate_backend_shift:
        simulation_impact += 12
    if simulate_cross_team_leadership:
        simulation_impact += 14
    if simulate_faang_prep:
        simulation_impact += 10

    explainable_probability = [
        {"label": "Readiness baseline fit", "impact_percent": readiness_impact},
        {"label": "System design depth", "impact_percent": design_impact},
        {"label": "Leadership exposure", "impact_percent": leadership_impact},
        {"label": "Years of scope ownership", "impact_percent": scope_impact},
        {"label": "Strong coding foundations", "impact_percent": coding_impact},
        {"label": "Risk signals", "impact_percent": risk_impact},
        {"label": "Execution momentum", "impact_percent": execution_impact},
        {"label": "Target difficulty", "impact_percent": target_difficulty_impact},
    ]
    if simulation_impact:
        explainable_probability.append({"label": "Simulation scenario boost", "impact_percent": simulation_impact})

    probability = max(
        12,
        min(
            94,
            base_probability
            + readiness_impact
            + design_impact
            + leadership_impact
            + scope_impact
            + coding_impact
            + risk_impact
            + execution_impact
            + target_difficulty_impact
            + simulation_impact,
        ),
    )

    gap_analysis = _build_target_gaps(target_path, effective_skills, effective_experience_years, effective_priority_gaps)

    probability_lift_to_40 = [
        {"action": "Improve system design depth (2 design docs + review)", "expected_lift_percent": 12},
        {"action": "Lead one cross-team architecture initiative", "expected_lift_percent": 9},
        {"action": "Increase backend ownership in current role", "expected_lift_percent": 6},
    ]
    
    if simulate_backend_shift:
        probability_lift_to_40 = [
            {"action": "Own end-to-end backend service with production SLAs", "expected_lift_percent": 14},
            {"action": "Implement distributed caching and async job processing", "expected_lift_percent": 10},
            {"action": "Document API performance optimization case study with metrics", "expected_lift_percent": 8},
        ]
    elif simulate_cross_team_leadership:
        if target_path == "engineering manager":
            probability_lift_to_40 = [
                {"action": "Lead cross-team quarterly planning with measurable outcomes", "expected_lift_percent": 15},
                {"action": "Mentor 3+ engineers with documented growth and promotions", "expected_lift_percent": 11},
                {"action": "Own incident response and org-wide postmortem process", "expected_lift_percent": 8},
            ]
        else:
            probability_lift_to_40 = [
                {"action": "Lead cross-functional initiative affecting multiple teams", "expected_lift_percent": 13},
                {"action": "Mentor junior engineers and document impact", "expected_lift_percent": 9},
                {"action": "Drive technical decision-making for team roadmap", "expected_lift_percent": 7},
            ]
    elif simulate_faang_prep:
        probability_lift_to_40 = [
            {"action": "Complete 50+ LeetCode problems (medium/hard) with optimal solutions", "expected_lift_percent": 14},
            {"action": "Run 6+ full mock interview loops (DSA + System Design + Behavioral)", "expected_lift_percent": 12},
            {"action": "Build 2 system design case studies with trade-off analysis", "expected_lift_percent": 9},
        ]
    elif target_path == "engineering manager":
        probability_lift_to_40 = [
            {"action": "Lead planning + execution for one cross-team quarter project", "expected_lift_percent": 11},
            {"action": "Mentor 2 engineers and capture measurable outcomes", "expected_lift_percent": 9},
            {"action": "Own incident communication and postmortem process", "expected_lift_percent": 6},
        ]

    next_30_day_action_engine = [
        {"action": "Solve 10 system design problems with written trade-offs", "expected_lift_percent": 6, "window_days": 30},
        {"action": "Lead 1 architecture discussion and publish notes", "expected_lift_percent": 4, "window_days": 21},
        {"action": "Ship 2 design docs tied to business metrics", "expected_lift_percent": 3, "window_days": 30},
    ]
    
    if simulate_backend_shift:
        next_30_day_action_engine = [
            {"action": "Build production-grade backend API with auth, rate limiting, and monitoring", "expected_lift_percent": 9, "window_days": 30},
            {"action": "Implement Redis caching layer and document performance gains", "expected_lift_percent": 7, "window_days": 21},
            {"action": "Write 3 architecture decision records (ADRs) for backend trade-offs", "expected_lift_percent": 5, "window_days": 30},
        ]
    elif simulate_cross_team_leadership:
        if target_path == "engineering manager":
            next_30_day_action_engine = [
                {"action": "Lead sprint planning for 2+ teams and track velocity metrics", "expected_lift_percent": 10, "window_days": 30},
                {"action": "Conduct 1:1s with 3 engineers and create growth plans", "expected_lift_percent": 8, "window_days": 30},
                {"action": "Run incident postmortem and implement process improvements", "expected_lift_percent": 6, "window_days": 21},
            ]
        else:
            next_30_day_action_engine = [
                {"action": "Lead technical initiative spanning 2+ teams with documented outcomes", "expected_lift_percent": 9, "window_days": 30},
                {"action": "Mentor 2 junior engineers on system design and code quality", "expected_lift_percent": 7, "window_days": 30},
                {"action": "Present technical proposal to leadership with business impact", "expected_lift_percent": 5, "window_days": 21},
            ]
    elif simulate_faang_prep:
        next_30_day_action_engine = [
            {"action": "Solve 40 LeetCode problems (20 medium, 15 hard, 5 expert)", "expected_lift_percent": 10, "window_days": 30},
            {"action": "Complete 5 full mock interview loops with feedback", "expected_lift_percent": 8, "window_days": 30},
            {"action": "Create 3 system design case studies (social network, payment system, video streaming)", "expected_lift_percent": 6, "window_days": 30},
        ]
    elif target_path == "faang engineer":
        next_30_day_action_engine = [
            {"action": "Complete 30 focused DSA problems with mock constraints", "expected_lift_percent": 7, "window_days": 30},
            {"action": "Run 4 full FAANG-style mock loops", "expected_lift_percent": 6, "window_days": 30},
            {"action": "Build one design case-study deck with Q&A prep", "expected_lift_percent": 4, "window_days": 21},
        ]

    eta_adjustment = int((100 - probability) / 15)
    progress_reduction = 2 if tracker_completion >= 40 else 1 if tracker_completion >= 20 else 0
    time_to_achieve = max(4, base_timeline + eta_adjustment - progress_reduction)

    confidence = "high" if probability >= 70 else "medium" if probability >= 45 else "low"
    factors = {
        "base_probability": base_probability,
        "execution_progress_percent": int((tracker_completion + checklist_completion) / 2),
        "high_risk_signals": high_risk_count,
        "medium_risk_signals": medium_risk_count,
        "effective_experience_years": round(effective_experience_years, 1),
        "simulation_flags_active": int(simulate_backend_shift) + int(simulate_cross_team_leadership) + int(simulate_faang_prep),
    }
    summary = (
        f"{target_path} trajectory currently sits at {probability}% probability with {confidence} confidence. "
        f"With focused execution on the next 30-day action engine, ETA is about {time_to_achieve} months."
    )
    if scenario_notes:
        summary = f"{summary} Scenario assumptions: {', '.join(scenario_notes)}."

    # Get audit_id for tracking
    audit_id = None
    with get_db_connection() as conn:
        latest_audit_row = conn.execute("SELECT id FROM audit_runs ORDER BY id DESC LIMIT 1").fetchone()
        if latest_audit_row:
            audit_id = latest_audit_row["id"]
    
    # Enhance with LLM for personalized insights
    llm_enhanced_gps = enhance_career_gps_with_llm(
        current_role=current_role,
        target_path=target_path,
        inferred_skills=inferred_skills,
        experience_years=effective_experience_years,
        priority_gaps=effective_priority_gaps,
        risks=risks,
        simulation_flags={
            "simulate_backend_shift": simulate_backend_shift,
            "simulate_cross_team_leadership": simulate_cross_team_leadership,
            "simulate_faang_prep": simulate_faang_prep,
        },
        base_probability=probability,
        base_timeline_months=time_to_achieve,
        audit_id=audit_id,
    )
    
    key_insight = None
    if llm_enhanced_gps:
        try:
            # Apply LLM's adjustments
            prob_adjustment = int(llm_enhanced_gps.get("probability_adjustment_percent", 0))
            timeline_adjustment = int(llm_enhanced_gps.get("timeline_adjustment_months", 0))
            
            # Adjust probability and timeline with LLM's insights
            probability = max(12, min(94, probability + prob_adjustment))
            time_to_achieve = max(4, time_to_achieve + timeline_adjustment)
            confidence = "high" if probability >= 70 else "medium" if probability >= 45 else "low"
            
            # Use LLM's gap analysis if provided
            llm_gaps = llm_enhanced_gps.get("gap_analysis")
            if isinstance(llm_gaps, list) and llm_gaps:
                gap_analysis = [str(gap).strip() for gap in llm_gaps if str(gap).strip()][:5]
            
            # Use LLM's action recommendations if provided
            llm_lift_actions = llm_enhanced_gps.get("probability_lift_actions")
            if isinstance(llm_lift_actions, list) and llm_lift_actions:
                probability_lift_to_40 = []
                for action_item in llm_lift_actions[:3]:
                    if isinstance(action_item, dict):
                        probability_lift_to_40.append({
                            "action": str(action_item.get("action", "")).strip(),
                            "expected_lift_percent": int(action_item.get("expected_lift_percent", 5)),
                        })
            
            # Use LLM's 30-day actions if provided
            llm_30day_actions = llm_enhanced_gps.get("next_30_day_actions")
            if isinstance(llm_30day_actions, list) and llm_30day_actions:
                next_30_day_action_engine = []
                for action_item in llm_30day_actions[:3]:
                    if isinstance(action_item, dict):
                        next_30_day_action_engine.append({
                            "action": str(action_item.get("action", "")).strip(),
                            "expected_lift_percent": int(action_item.get("expected_lift_percent", 5)),
                            "window_days": int(action_item.get("window_days", 30)),
                        })
            
            # Use LLM's summary if provided
            llm_summary = llm_enhanced_gps.get("trajectory_summary")
            if isinstance(llm_summary, str) and llm_summary.strip():
                summary = llm_summary.strip()
            
            # Extract key insight
            key_insight = llm_enhanced_gps.get("key_insight")
            if isinstance(key_insight, str):
                key_insight = key_insight.strip() or None
                
        except Exception:
            pass

    return CareerGPSResponse(
        current_role=current_role,
        target_path=target_path,
        gap_analysis=gap_analysis,
        success_probability_percent=probability,
        time_to_achieve_months=time_to_achieve,
        confidence=confidence,
        factors=factors,
        explainable_probability=explainable_probability,
        probability_lift_to_40=probability_lift_to_40,
        next_30_day_action_engine=next_30_day_action_engine,
        simulation_used={
            "backend_shift": simulate_backend_shift,
            "cross_team_leadership": simulate_cross_team_leadership,
            "faang_prep": simulate_faang_prep,
        },
        summary=summary,
        key_insight=key_insight,
        claude_enhanced=llm_enhanced_gps is not None,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/test-llm")
def test_llm() -> dict[str, Any]:
    provider = LLMFactory.get_provider()
    if not provider:
        return {
            "status": "error",
            "message": "No LLM provider configured. Set ANTHROPIC_API_KEY, GOOGLE_API_KEY, or OPENAI_API_KEY",
            "provider_type": os.getenv("LLM_PROVIDER", "claude"),
        }
    
    try:
        response_text = generate_with_llm(
            prompt='Say "LLM is working!" in JSON format: {"message": "..."}',
            max_tokens=100,
            temperature=0.2,
        )
        return {
            "status": "success",
            "provider": provider.get_provider_name(),
            "response": response_text,
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "provider": provider.get_provider_name()}


@app.get("/")
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/action-plan")
def action_plan_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "action-plan.html")


@app.get("/execution-tracker")
def execution_tracker_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "execution-tracker.html")


@app.get("/career-gps")
def career_gps_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "career-gps.html")


@app.get("/audits/recent")
def recent_audits(limit: int = 5) -> dict[str, list[dict[str, object]]]:
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT created_at, inferred_role, target_role, readiness_score, timeline_months
            FROM audit_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 20)),),
        ).fetchall()

    return {
        "audits": [
            {
                "created_at": row["created_at"],
                "inferred_role": row["inferred_role"],
                "target_role": row["target_role"],
                "readiness_score": row["readiness_score"],
                "timeline_months": row["timeline_months"],
            }
            for row in rows
        ]
    }


@app.get("/audits/latest")
def latest_audit() -> dict[str, object]:
    return {"audit": get_latest_audit_payload()}


@app.get("/career-gps/data", response_model=CareerGPSResponse)
def career_gps_data(
    target: Optional[str] = None,
    simulate_backend_shift: bool = False,
    simulate_cross_team_leadership: bool = False,
    simulate_faang_prep: bool = False,
) -> CareerGPSResponse:
    latest = get_latest_audit_payload()
    if not latest:
        raise HTTPException(status_code=404, detail="No audit found. Generate an audit first.")
    return compute_career_gps(
        latest,
        target,
        simulate_backend_shift=simulate_backend_shift,
        simulate_cross_team_leadership=simulate_cross_team_leadership,
        simulate_faang_prep=simulate_faang_prep,
    )


@app.get("/tracker/items", response_model=TrackerItemsResponse)
def tracker_items() -> TrackerItemsResponse:
    return fetch_tracker_items()


@app.patch("/tracker/items/{item_id}", response_model=TrackerItemsResponse)
def update_tracker_item(item_id: int, payload: TrackerStatusUpdate) -> TrackerItemsResponse:
    allowed_statuses = {"todo", "in_progress", "done"}
    if payload.status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Invalid status. Use todo, in_progress, or done.")

    completed_at: Optional[str] = None
    if payload.status == "done":
        completed_at = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        cursor = conn.execute("SELECT id FROM tracker_items WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tracker item not found.")

        conn.execute(
            """
            UPDATE tracker_items
            SET status = ?, completed_at = ?
            WHERE id = ?
            """,
            (payload.status, completed_at, item_id),
        )
        conn.commit()

    return fetch_tracker_items()


@app.get("/checklist/30days", response_model=ChecklistResponse)
def checklist_30_days() -> ChecklistResponse:
    return fetch_30_day_checklist()


@app.patch("/checklist/30days/{item_id}", response_model=ChecklistResponse)
def update_checklist_item(item_id: int, payload: ChecklistStatusUpdate) -> ChecklistResponse:
    allowed_statuses = {"todo", "in_progress", "done"}
    if payload.status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Invalid status. Use todo, in_progress, or done.")

    completed_at: Optional[str] = None
    if payload.status == "done":
        completed_at = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        cursor = conn.execute("SELECT id FROM checklist_items WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Checklist item not found.")

        conn.execute(
            """
            UPDATE checklist_items
            SET status = ?, completed_at = ?
            WHERE id = ?
            """,
            (payload.status, completed_at, item_id),
        )
        conn.commit()

    return fetch_30_day_checklist()


class GPSFeedback(BaseModel):
    feedback_score: int = Field(ge=1, le=5, description="1-5 rating")
    feedback_text: Optional[str] = Field(default=None, description="Optional feedback text")


@app.post("/career-gps/feedback/{interaction_id}")
def submit_gps_feedback(interaction_id: int, feedback: GPSFeedback) -> dict[str, str]:
    with get_db_connection() as conn:
        cursor = conn.execute(
            "SELECT id FROM claude_gps_interactions WHERE id = ?", (interaction_id,)
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Interaction not found.")
        
        conn.execute(
            """
            UPDATE claude_gps_interactions
            SET user_feedback = ?, feedback_score = ?
            WHERE id = ?
            """,
            (feedback.feedback_text, feedback.feedback_score, interaction_id),
        )
        conn.commit()
    
    return {"status": "ok", "message": "Feedback recorded for fine-tuning."}


@app.get("/career-gps/training-data")
def export_training_data(min_score: int = 4, limit: int = 100) -> dict[str, list[dict[str, Any]]]:
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT 
                created_at,
                current_role,
                target_path,
                simulation_flags,
                input_context,
                claude_response,
                base_probability,
                adjusted_probability,
                base_timeline_months,
                adjusted_timeline_months,
                user_feedback,
                feedback_score
            FROM claude_gps_interactions
            WHERE feedback_score >= ? OR feedback_score IS NULL
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (min_score, limit),
        ).fetchall()
    
    training_examples = []
    for row in rows:
        try:
            training_examples.append({
                "created_at": row["created_at"],
                "current_role": row["current_role"],
                "target_path": row["target_path"],
                "simulation_flags": json.loads(row["simulation_flags"]),
                "input_context": json.loads(row["input_context"]),
                "claude_response": json.loads(row["claude_response"]),
                "base_probability": row["base_probability"],
                "adjusted_probability": row["adjusted_probability"],
                "base_timeline_months": row["base_timeline_months"],
                "adjusted_timeline_months": row["adjusted_timeline_months"],
                "user_feedback": row["user_feedback"],
                "feedback_score": row["feedback_score"],
            })
        except (json.JSONDecodeError, KeyError):
            continue
    
    return {"training_examples": training_examples, "count": len(training_examples)}


@app.post("/audit", response_model=AuditResponse)
async def create_audit(
    resume: UploadFile = File(...),
    current_salary_lpa: float = Form(..., gt=0),
    years_experience: Optional[float] = Form(default=None, ge=0),
    target_role: Optional[str] = Form(default=None),
) -> AuditResponse:
    if resume.filename is None:
        raise HTTPException(status_code=400, detail="Resume file is required.")

    raw = await resume.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded resume is empty.")

    resume_text = sanitize_text(extract_text_from_upload(resume, raw))
    if not resume_text:
        raise HTTPException(status_code=400, detail="Could not parse resume text.")
    is_valid_resume, validation_error = validate_resume_text(resume_text)
    if not is_valid_resume:
        raise HTTPException(status_code=400, detail=validation_error)

    if current_salary_lpa < 2 or current_salary_lpa > 500:
        raise HTTPException(
            status_code=400,
            detail="Current salary looks invalid. Enter salary in LPA between 2 and 500.",
        )

    target_role_value = sanitize_text(target_role) if target_role else None
    if target_role_value == "":
        target_role_value = None

    # Step 1: Try LLM-first audit (Claude/Gemini/OpenAI)
    llm_audit = audit_with_llm(resume_text, current_salary_lpa, years_experience, target_role_value)
    llm_enhanced = False
    
    if llm_audit:
        # Use LLM's analysis as primary source
        try:
            inferred_role = str(llm_audit.get("inferred_current_role", "")).strip()
            inferred_experience = float(llm_audit.get("inferred_years_experience", 3.0))
            
            # Validate LLM's experience inference - if user provided experience, use that as ground truth
            if years_experience is not None:
                inferred_experience = years_experience
                print(f"[INFO] Using user-provided experience: {years_experience} years (overriding LLM inference)")
            else:
                # Validate LLM inference is reasonable (0.5 to 30 years)
                if inferred_experience < 0.5 or inferred_experience > 30:
                    print(f"[WARN] LLM inferred unreasonable experience: {inferred_experience}, using fallback")
                    inferred_experience = infer_years_experience(resume_text, None)
                else:
                    print(f"[INFO] Using LLM-inferred experience: {inferred_experience} years")
            
            # Extract skills from LLM
            llm_skills = llm_audit.get("inferred_skills", {})
            skills = {
                "frontend": [str(s).strip() for s in llm_skills.get("frontend", [])],
                "backend": [str(s).strip() for s in llm_skills.get("backend", [])],
                "system_design": [str(s).strip() for s in llm_skills.get("system_design", [])],
                "leadership": [str(s).strip() for s in llm_skills.get("leadership", [])],
            }
            
            # Use LLM's readiness score
            readiness_score = int(llm_audit.get("readiness_score", 50))
            readiness_score = max(25, min(92, readiness_score))
            
            # Extract priority gaps from LLM
            priority_gaps = [str(gap).strip() for gap in llm_audit.get("priority_gaps", []) if str(gap).strip()][:4]
            
            # Extract risks from LLM
            risks = []
            for risk_data in llm_audit.get("career_risk_signals", [])[:3]:
                if isinstance(risk_data, dict):
                    severity = str(risk_data.get("severity", "medium")).lower()
                    if severity not in {"low", "medium", "high"}:
                        severity = "medium"
                    risks.append(
                        CareerRiskSignal(
                            severity=severity,
                            signal=str(risk_data.get("signal", "")).strip() or "Career signal",
                            reason=str(risk_data.get("reason", "")).strip() or "Needs analysis",
                            mitigation=str(risk_data.get("mitigation", "")).strip() or "Take action",
                        )
                    )
            
            # Extract action plan from LLM
            action_plan = []
            for plan_item in llm_audit.get("action_plan", [])[:3]:
                if isinstance(plan_item, dict):
                    category = str(plan_item.get("category", "learn")).lower()
                    if category not in {"learn", "build", "apply"}:
                        category = "learn"
                    details = [str(d).strip() for d in plan_item.get("details", []) if str(d).strip()][:5]
                    action_plan.append(
                        ActionPlanItem(
                            category=category,
                            title=str(plan_item.get("title", "")).strip() or "Career action",
                            details=details or ["Define specific steps"],
                            expected_impact=str(plan_item.get("expected_impact", "")).strip() or "Improves readiness",
                        )
                    )
            
            # Extract execution tracker from LLM
            llm_tracker_items = []
            for tracker_item in llm_audit.get("execution_tracker", []):
                if isinstance(tracker_item, dict):
                    category = str(tracker_item.get("category", "learn")).lower()
                    if category not in {"learn", "build", "apply"}:
                        category = "learn"
                    llm_tracker_items.append({
                        "title": str(tracker_item.get("title", "")).strip() or "Task",
                        "category": category,
                        "week": max(1, min(4, int(tracker_item.get("week", 1)))),
                        "source_gap": str(tracker_item.get("source_gap", "")).strip() or "General improvement",
                    })
            
            # Extract 30-day checklist from LLM
            llm_checklist_items = []
            for checklist_item in llm_audit.get("checklist_30day", []):
                if isinstance(checklist_item, dict):
                    category = str(checklist_item.get("category", "learn")).lower()
                    if category not in {"learn", "build", "apply"}:
                        category = "learn"
                    day = int(checklist_item.get("day", 3))
                    if day not in {3, 7, 14, 21, 30}:
                        day = 3
                    llm_checklist_items.append({
                        "title": str(checklist_item.get("title", "")).strip() or "Milestone",
                        "day": day,
                        "category": category,
                    })
            
            # Get track and rationale from LLM
            action_plan_track = str(llm_audit.get("action_plan_track", "balanced_fullstack")).strip()
            action_plan_rationale = str(llm_audit.get("action_plan_rationale", "")).strip() or "Customized based on profile"
            
            # Get timeline from LLM
            timeline_months = int(llm_audit.get("timeline_months", 9))
            timeline_confidence = str(llm_audit.get("timeline_confidence", "medium")).strip()
            timeline_summary = str(llm_audit.get("timeline_summary", "")).strip()
            
            llm_enhanced = True
            
        except Exception as e:
            print(f"Error parsing LLM audit: {e}")
            llm_audit = None
    
    # Step 2: Fallback to rule-based if LLM fails or enhance LLM's output
    if not llm_audit or not llm_enhanced:
        inferred_experience = infer_years_experience(resume_text, years_experience)
        skills = infer_skills(resume_text)
        inferred_role = infer_current_role(skills, inferred_experience)
        priority_gaps = build_priority_gaps(skills, inferred_experience, target_role_value)
        risks = build_risk_signals(skills, inferred_experience, inferred_role, target_role_value)
        readiness_score, score_breakdown, score_explanation = calculate_readiness_score(
            skills, risks, inferred_experience, target_role_value
        )
        action_plan, action_plan_track, action_plan_rationale = build_action_plan(
            skills, inferred_role, target_role_value, priority_gaps, inferred_experience
        )
        timeline_months = 9
        timeline_confidence = "medium"
        timeline_summary = ""
        # Initialize empty LLM items for fallback
        llm_tracker_items = []
        llm_checklist_items = []
    
    # Step 3: Backend refinement and validation
    role_for_benchmark = normalize_role(target_role_value) if target_role_value else inferred_role
    salary_check = salary_reality_check(current_salary_lpa, role_for_benchmark, inferred_experience)
    band = get_benchmark_band(role_for_benchmark, inferred_experience)
    
    # Refine timeline with backend logic
    if not timeline_summary:
        timeline = timeline_prediction(current_salary_lpa, band, risks, inferred_experience)
        timeline_months = timeline.timeline_months
        timeline_confidence = timeline.confidence
        timeline_summary = timeline.summary
    
    # Calculate score breakdown (backend validation)
    _, score_breakdown, score_explanation = calculate_readiness_score(
        skills, risks, inferred_experience, target_role_value
    )
    
    # Ensure we have valid action plan
    if not action_plan or len(action_plan) == 0:
        action_plan, action_plan_track, action_plan_rationale = build_action_plan(
            skills, inferred_role, target_role_value, priority_gaps, inferred_experience
        )
    
    # Ensure we have valid gaps
    if not priority_gaps or len(priority_gaps) == 0:
        priority_gaps = build_priority_gaps(skills, inferred_experience, target_role_value)
    
    # Ensure we have valid risks
    if not risks or len(risks) == 0:
        risks = build_risk_signals(skills, inferred_experience, inferred_role, target_role_value)
    
    # Create timeline object
    timeline = TimelinePrediction(
        target_comp_lpa=round(band.max_lpa * 0.9, 1),
        timeline_months=timeline_months,
        confidence=timeline_confidence,
        assumptions=[
            "8-10 focused hours/week on upskilling and interview prep.",
            "Consistent applications and referral outreach every week.",
            "At least one high-quality portfolio project shipped in 60 days.",
        ],
        summary=timeline_summary or f"Estimated timeline of {timeline_months} months with {timeline_confidence} confidence.",
    )

    result = AuditResponse(
        inferred_current_role=inferred_role,
        inferred_years_experience=inferred_experience,
        requested_target_role=target_role_value,
        inferred_skills=skills,
        readiness_score=readiness_score,
        score_breakdown=score_breakdown,
        score_explanation=score_explanation,
        priority_gaps=priority_gaps,
        action_plan_track=action_plan_track,
        action_plan_rationale=action_plan_rationale,
        salary_reality_check=salary_check,
        career_risk_signals=risks,
        action_plan=action_plan,
        timeline_prediction=timeline,
        llm_enhanced=llm_enhanced,
    )

    audit_id = save_audit_run(
        current_salary_lpa=current_salary_lpa,
        years_experience=inferred_experience,
        target_role=target_role_value,
        inferred_role=inferred_role,
        readiness_score=readiness_score,
        underpaid_min=salary_check.estimated_gap_lpa["min"],
        underpaid_max=salary_check.estimated_gap_lpa["max"],
        timeline_months=timeline.timeline_months,
        audit_payload=json.dumps(result.model_dump()),
    )
    upsert_tracker_items(audit_id, action_plan, priority_gaps, llm_tracker_items)
    upsert_30_day_checklist(audit_id, action_plan, llm_checklist_items)

    return result
