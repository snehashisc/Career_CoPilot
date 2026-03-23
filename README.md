# Career CoPilot MVP

FastAPI MVP for a "Career Audit + Action Plan" product.

## What this MVP does

- Accepts resume upload + current salary + optional target role.
- Infers years of experience from resume text (with safe fallback).
- Returns:
  - Readiness score and top capability gaps
  - Action-plan track and rationale
  - Score explainability (dimension breakdown + explanation lines)
  - Salary reality check
  - Career risk signals
  - Specific action plan (learn/build/apply)
  - Timeline prediction
- Stores benchmark data and audit runs in local SQLite (`career_copilot.db`).
- Maintains an execution tracker checklist with status updates.
- Includes a 30-day checklist with progress toggles.

## Quick start

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run server:

```bash
uvicorn main:app --reload --port 8000
```

4. Open web app:

`http://127.0.0.1:8000/`

5. Optional API docs:

`http://127.0.0.1:8000/docs`

## Claude 3.5 Sonnet integration

Set an Anthropic API key to enable LLM refinement in `/audit`:

```bash
export ANTHROPIC_API_KEY="your_key_here"
```

Model used: `claude-3-5-sonnet-20241022`

Without API key, the app safely falls back to deterministic rule-based analysis.

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

## Notes

- Resume parsing now supports plain text, PDF, and DOCX extraction.
- Invalid/non-resume uploads are rejected with clear validation errors.
- Salary benchmarks are seeded in SQLite and filtered by role + experience.
- Recommendations are still rule-based and should later be tuned with real user outcome data.
