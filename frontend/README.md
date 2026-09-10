# Spoken Tutorial Generator - frontend

Covers the two HLD screens (§9.3) that have real backend support today:
**Script Workspace & Segment Editor** and **Timeline, Preview & Sync Review**.
No login, project dashboard, voice/lexicon management or render queue -
see `../backend/README.md` for what the pipeline actually does and which
stages are still stubs.

## Run it

```bash
# backend, in one terminal
cd backend
uvicorn app.api:app --reload --port 8123

# frontend, in another
cd frontend
npm install
npm run dev    # http://localhost:5173
```

Upload `../Timed-script-sample-english.docx` (language `en`, duration
`663.2`) or `../Tamil-script-sample.docx` (language `ta`) on the Script tab,
inspect the parsed segments and budgets, then generate narration for a target
language to see the Timeline tab's QA report. The pipeline's translator and
TTS are still stubs (`echo`/`silent`) - the "STUBBED STAGES" banner on the
Timeline tab says so, same as the CLI.

## Stack

React 18 + TypeScript + Vite + Tailwind, per HLD §10.1. `src/api/types.ts`
mirrors `backend/app/schemas.py` field-for-field; `src/api/client.ts` is thin
fetch wrappers around the three endpoints in `backend/app/api.py`.
