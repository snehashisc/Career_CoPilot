# Career CoPilot MVP

AI-powered career guidance platform for software engineers. FastAPI backend with LLM integration for personalized resume audits, action plans, and career trajectory analysis.

## Features

### 🎯 AI-Powered Resume Auditing
- Analyzes resume using LLM (Gemini, Claude, or OpenAI)
- Infers current role, experience level, and skill strengths
- Calculates readiness score (25-92) for target roles
- Identifies priority gaps and career risk signals
- Provides salary reality check based on market data

### 📋 Personalized Action Plans
- **3 Action Items**: Learn, Build, Apply categories
- **Execution Tracker**: 8-10 weekly tasks (LLM-generated)
- **30-Day Checklist**: 5 milestone items at strategic days
- All recommendations tailored to individual profile

### 🧭 Career GPS
- Interactive trajectory analysis for different career paths
- Simulations for backend shifts, leadership moves, FAANG prep
- Success probability and timeline predictions
- Gap analysis with specific recommendations

### 💾 Data Persistence
- SQLite database for audit history and progress tracking
- Execution tracker with status updates (todo/in_progress/done)
- 30-day checklist with completion tracking
- Audit-specific data (no cross-contamination)

## Quick Start

### 1. Install Dependencies

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install packages
pip install -r requirements.txt
```

### 2. Configure LLM Provider

Create a `.env` file in the project root:

```bash
# Choose your LLM provider (gemini, claude, or openai)
LLM_PROVIDER=gemini

# Add corresponding API key
GOOGLE_API_KEY=your_google_api_key_here

# Alternative providers:
# ANTHROPIC_API_KEY=your_claude_key_here
# OPENAI_API_KEY=your_openai_key_here
```

**Get API Keys:**
- **Gemini** (Recommended - Free tier): https://aistudio.google.com/app/apikey
- **Claude**: https://console.anthropic.com/
- **OpenAI**: https://platform.openai.com/api-keys

### 3. Run Server

```bash
uvicorn main:app --reload --port 8000
```

### 4. Access Application

- **Web App**: http://127.0.0.1:8000/
- **API Docs**: http://127.0.0.1:8000/docs
- **Test LLM**: http://127.0.0.1:8000/test-llm

## LLM Provider Support

The application uses a **provider-agnostic architecture** - switch between LLM providers with zero code changes:

| Provider | Model | Cost/Audit | Free Tier |
|----------|-------|------------|-----------|
| **Gemini** | gemini-2.5-flash | ~$0.01 | ✅ 60 req/min |
| **Claude** | claude-3-5-sonnet | ~$0.05 | Trial credits |
| **OpenAI** | gpt-4o | ~$0.04 | $5 credits |

**Fallback**: If no LLM is configured, the system automatically uses rule-based analysis.

See `LLM_PROVIDER_GUIDE.md` for detailed switching instructions.

## Deploy on Vercel

This project includes `vercel.json` and can be deployed as-is.

1. Install Vercel CLI:

```bash
npm i -g vercel
```

2. Deploy from project root:

```bash
vercel
```

3. For production deploy:

```bash
vercel --prod
```

### Important note on data

- On Vercel, SQLite uses `/tmp/career_copilot.db` (ephemeral storage).
- This means benchmark seeding works, but audit history is not guaranteed to persist across cold starts.
- For persistent history in production, move to Postgres/Supabase in the next step.

## API

### `POST /audit`

Multipart form fields:

- `resume` (file, required)
- `current_salary_lpa` (number, required)
- `years_experience` (number, optional; if omitted it is inferred from resume)
- `target_role` (string, optional)

### `GET /health`

Returns service health status.

### `GET /`

Serves the MVP intake + report UI.

### `GET /action-plan`

Serves a dedicated action-plan detail page.

### `GET /execution-tracker`

Serves a dedicated execution-tracker detail page.

### `GET /career-gps`

Serves a dedicated Career GPS page.

### `GET /audits/recent`

Returns recent audit history to support progress tracking in UI.

### `GET /audits/latest`

Returns the latest full audit payload (used by the action-plan page fallback on refresh).

### `GET /career-gps/data`

Returns live trajectory analysis (gap analysis, success probability, ETA) for a target path.

Optional query params:

- `target` (`staff engineer` / `engineering manager` / `faang engineer`)
- `simulate_backend_shift` (bool)
- `simulate_cross_team_leadership` (bool)
- `simulate_faang_prep` (bool)

### `GET /tracker/items`

Returns execution tracker items and completion percentage.

### `PATCH /tracker/items/{item_id}`

Updates tracker item status (`todo`, `in_progress`, `done`).

### `GET /checklist/30days`

Returns day-wise 30-day checklist items and completion percentage.

### `PATCH /checklist/30days/{item_id}`

Updates 30-day checklist item status (`todo`, `in_progress`, `done`).

## Project Structure

```
Career CoPilot/
├── main.py                      # FastAPI backend
├── llm_provider.py              # LLM abstraction layer
├── static/                      # Frontend HTML/CSS/JS
│   ├── index.html              # Resume upload & audit
│   ├── action-plan.html        # Action plan & checklist
│   ├── execution-tracker.html  # Weekly task tracker
│   └── career-gps.html         # Trajectory simulations
├── career_copilot.db           # SQLite database
├── .env                        # API keys (not in git)
└── requirements.txt            # Python dependencies
```

## Documentation

- **`LLM_PROVIDER_GUIDE.md`** - How to switch between LLM providers
- **`LLM_TRACKER_CHECKLIST.md`** - LLM-generated tracker/checklist details
- **`PROVIDER_COMPARISON.md`** - Detailed provider comparison
- **`IMPLEMENTATION_STATUS.md`** - Current feature status

## Technical Notes

- **Resume Parsing**: Supports PDF, DOCX, and plain text
- **Validation**: Rejects invalid/non-resume uploads
- **Salary Benchmarks**: Seeded in SQLite, filtered by role + experience
- **LLM Integration**: Primary analysis with rule-based fallback
- **Audit Scoping**: Tracker/checklist items are audit-specific (no cross-contamination)
- **Optimistic UI**: Immediate updates without flickering
