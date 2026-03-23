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
from anthropic import Anthropic
from docx import Document
from pydantic import BaseModel, Field
from pypdf import PdfReader


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
    factors: dict[str, int]
    explainable_probability: list[dict[str, object]]
    probability_lift_to_40: list[dict[str, object]]
    next_30_day_action_engine: list[dict[str, object]]
    simulation_used: dict[str, object]
    summary: str


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
                created_at TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                week INTEGER NOT NULL,
                status TEXT NOT NULL,
                source_gap TEXT NOT NULL,
                fingerprint TEXT NOT NULL UNIQUE,
                completed_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checklist_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                title TEXT NOT NULL,
                day INTEGER NOT NULL,
                category TEXT NOT NULL,
                status TEXT NOT NULL,
                fingerprint TEXT NOT NULL UNIQUE,
                completed_at TEXT
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


def refine_with_claude(
    resume_text: str,
    inferred_role: str,
    target_role: Optional[str],
    readiness_score: int,
    priority_gaps: list[str],
    risks: list[CareerRiskSignal],
    action_plan: list[ActionPlanItem],
    timeline: TimelinePrediction,
) -> Optional[dict[str, Any]]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    client = Anthropic(api_key=api_key)
    prompt_payload = {
        "inferred_role": inferred_role,
        "target_role": target_role,
        "readiness_score": readiness_score,
        "priority_gaps": priority_gaps,
        "risks": [risk.model_dump() for risk in risks],
        "action_plan": [item.model_dump() for item in action_plan],
        "timeline_summary": timeline.summary,
        "resume_excerpt": resume_text[:5000],
    }
    prompt = (
        "You are refining a career audit. Return ONLY valid JSON.\n"
        "Rules:\n"
        "- Keep recommendations concrete and non-redundant.\n"
        "- Do not invent facts not inferable from resume/context.\n"
        "- Max 4 priority gaps, max 3 risks, max 3 action items.\n"
        "- Timeline summary must be realistic and conditional.\n"
        "JSON shape:\n"
        "{\n"
        '  "priority_gaps": ["..."],\n'
        '  "career_risk_signals": [{"severity":"low|medium|high","signal":"...","reason":"...","mitigation":"..."}],\n'
        '  "action_plan": [{"category":"learn|build|apply","title":"...","details":["..."],"expected_impact":"..."}],\n'
        '  "timeline_summary": "..."\n'
        "}\n"
        f"Context JSON:\n{json.dumps(prompt_payload)}"
    )

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1400,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        text_chunks: list[str] = []
        for block in response.content:
            if hasattr(block, "text"):
                text_chunks.append(block.text)
        refined = _extract_json_object("\n".join(text_chunks))
        return refined
    except Exception:
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


def upsert_tracker_items(action_plan: list[ActionPlanItem], priority_gaps: list[str]) -> None:
    tracker_items = build_tracker_items(action_plan, priority_gaps)
    if not tracker_items:
        return

    with get_db_connection() as conn:
        for item in tracker_items:
            fingerprint = _fingerprint(f"{item['category']}::{item['title']}")
            conn.execute(
                """
                INSERT INTO tracker_items (
                    created_at, title, category, week, status, source_gap, fingerprint
                )
                VALUES (?, ?, ?, ?, 'todo', ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    week = excluded.week,
                    source_gap = excluded.source_gap
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    item["title"],
                    item["category"],
                    item["week"],
                    item["source_gap"],
                    fingerprint,
                ),
            )
        conn.commit()


def fetch_tracker_items() -> TrackerItemsResponse:
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, category, week, status, source_gap, created_at, completed_at
            FROM tracker_items
            ORDER BY
              CASE status
                WHEN 'in_progress' THEN 0
                WHEN 'todo' THEN 1
                WHEN 'done' THEN 2
                ELSE 3
              END,
              week ASC,
              id DESC
            """
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


def upsert_30_day_checklist(action_plan: list[ActionPlanItem]) -> None:
    checklist_items = build_30_day_checklist(action_plan)
    if not checklist_items:
        return

    with get_db_connection() as conn:
        for item in checklist_items:
            fingerprint = _fingerprint(f"{item['day']}::{item['category']}::{item['title']}")
            conn.execute(
                """
                INSERT INTO checklist_items (
                    created_at, title, day, category, status, fingerprint
                )
                VALUES (?, ?, ?, ?, 'todo', ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    day = excluded.day,
                    category = excluded.category
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    item["title"],
                    item["day"],
                    item["category"],
                    fingerprint,
                ),
            )
        conn.commit()


def fetch_30_day_checklist() -> ChecklistResponse:
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, day, category, status, created_at, completed_at
            FROM checklist_items
            ORDER BY day ASC, id DESC
            """
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

    tracker_completion = fetch_tracker_items().completion_percent
    checklist_completion = fetch_30_day_checklist().completion_percent
    high_risk_count = len([risk for risk in risks if risk.get("severity") == "high"])
    medium_risk_count = len([risk for risk in risks if risk.get("severity") == "medium"])

    # Explainable Probability Engine: start from neutral baseline and apply named contributions.
    base_probability = 50
    readiness_impact = int((readiness - 50) * 0.5)
    design_depth = len(inferred_skills.get("system_design", []))
    leadership_depth = len(inferred_skills.get("leadership", []))
    backend_depth = len(inferred_skills.get("backend", []))
    frontend_depth = len(inferred_skills.get("frontend", []))
    design_impact = -12 if design_depth == 0 else -6 if design_depth == 1 else 4
    leadership_impact = -10 if leadership_depth == 0 and target_path == "engineering manager" else -5 if leadership_depth == 0 else 4
    scope_impact = -8 if experience_years < 5 else -3 if experience_years < 7 else 5
    coding_impact = 6 if (backend_depth + frontend_depth) >= 4 else 2
    risk_impact = -((high_risk_count * 8) + (medium_risk_count * 4))
    execution_impact = int((tracker_completion * 0.16) + (checklist_completion * 0.12))
    target_difficulty_impact = {"staff engineer": -8, "engineering manager": -12, "faang engineer": -14}.get(
        target_path, -8
    )

    simulation_impact = 0
    if simulate_backend_shift:
        simulation_impact += 8
    if simulate_cross_team_leadership:
        simulation_impact += 9
    if simulate_faang_prep:
        simulation_impact += 7

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

    gap_analysis = _build_target_gaps(target_path, inferred_skills, experience_years, priority_gaps)

    probability_lift_to_40 = [
        {"action": "Improve system design depth (2 design docs + review)", "expected_lift_percent": 12},
        {"action": "Lead one cross-team architecture initiative", "expected_lift_percent": 9},
        {"action": "Increase backend ownership in current role", "expected_lift_percent": 6},
    ]
    if target_path == "engineering manager":
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
    if target_path == "faang engineer":
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
        "inferred_experience_years": int(experience_years),
    }
    summary = (
        f"{target_path} trajectory currently sits at {probability}% probability with {confidence} confidence. "
        f"With focused execution on the next 30-day action engine, ETA is about {time_to_achieve} months."
    )

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
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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

    inferred_experience = infer_years_experience(resume_text, years_experience)
    target_role_value = sanitize_text(target_role) if target_role else None
    if target_role_value == "":
        target_role_value = None

    skills = infer_skills(resume_text)
    inferred_role = infer_current_role(skills, inferred_experience)
    role_for_benchmark = normalize_role(target_role_value) if target_role_value else inferred_role

    salary_check = salary_reality_check(current_salary_lpa, role_for_benchmark, inferred_experience)
    risks = build_risk_signals(skills, inferred_experience, inferred_role, target_role_value)
    priority_gaps = build_priority_gaps(skills, inferred_experience, target_role_value)
    readiness_score, score_breakdown, score_explanation = calculate_readiness_score(
        skills, risks, inferred_experience, target_role_value
    )
    action_plan, action_plan_track, action_plan_rationale = build_action_plan(
        skills, inferred_role, target_role_value, priority_gaps, inferred_experience
    )
    band = get_benchmark_band(role_for_benchmark, inferred_experience)
    timeline = timeline_prediction(current_salary_lpa, band, risks, inferred_experience)
    llm_enhanced = False

    refined = refine_with_claude(
        resume_text=resume_text,
        inferred_role=inferred_role,
        target_role=target_role_value,
        readiness_score=readiness_score,
        priority_gaps=priority_gaps,
        risks=risks,
        action_plan=action_plan,
        timeline=timeline,
    )
    if refined:
        try:
            candidate_gaps = refined.get("priority_gaps")
            if isinstance(candidate_gaps, list):
                priority_gaps = [str(gap).strip() for gap in candidate_gaps if str(gap).strip()][:4] or priority_gaps

            candidate_risks = refined.get("career_risk_signals")
            if isinstance(candidate_risks, list):
                parsed_risks: list[CareerRiskSignal] = []
                for risk in candidate_risks[:3]:
                    if not isinstance(risk, dict):
                        continue
                    severity = str(risk.get("severity", "medium")).lower()
                    if severity not in {"low", "medium", "high"}:
                        severity = "medium"
                    parsed_risks.append(
                        CareerRiskSignal(
                            severity=severity,
                            signal=str(risk.get("signal", "Career signal")).strip() or "Career signal",
                            reason=str(risk.get("reason", "Needs deeper evidence.")).strip() or "Needs deeper evidence.",
                            mitigation=str(risk.get("mitigation", "Strengthen this area with measurable projects.")).strip()
                            or "Strengthen this area with measurable projects.",
                        )
                    )
                if parsed_risks:
                    risks = parsed_risks

            candidate_plan = refined.get("action_plan")
            if isinstance(candidate_plan, list):
                parsed_plan: list[ActionPlanItem] = []
                for item in candidate_plan[:3]:
                    if not isinstance(item, dict):
                        continue
                    category = str(item.get("category", "learn")).lower()
                    if category not in {"learn", "build", "apply"}:
                        category = "learn"
                    details_raw = item.get("details", [])
                    details = [str(detail).strip() for detail in details_raw if str(detail).strip()] if isinstance(details_raw, list) else []
                    parsed_plan.append(
                        ActionPlanItem(
                            category=category,
                            title=str(item.get("title", "Career action")).strip() or "Career action",
                            details=details[:5] if details else ["Define one concrete next step tied to this action."],
                            expected_impact=str(item.get("expected_impact", "Improves role readiness.")).strip()
                            or "Improves role readiness.",
                        )
                    )
                if parsed_plan:
                    action_plan = parsed_plan

            timeline_summary = refined.get("timeline_summary")
            if isinstance(timeline_summary, str) and timeline_summary.strip():
                timeline.summary = timeline_summary.strip()

            llm_enhanced = True
        except Exception:
            llm_enhanced = False

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

    _audit_id = save_audit_run(
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
    upsert_tracker_items(action_plan, priority_gaps)
    upsert_30_day_checklist(action_plan)

    return result
