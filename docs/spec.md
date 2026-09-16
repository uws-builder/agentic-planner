# Agentic Media Planner — Spec

Status: **draft, evolving**
Last updated: 2026-09-16

This is the living reference for what we're building and why. Update it as decisions get made — treat unresolved questions as open until answered here, not just in chat.

## 1. Problem & User

**Who is this for?**
_TBD — you personally, an agency media planner, a brand-side marketer?_

**What painful workflow does this replace?**
_TBD — what does someone do today without this tool? Spreadsheets, an existing tool, gut instinct?_

## 2. Scope Boundary

Media planning, buying, and measurement are three different problems. For v1:

- **Planning** (recommend channel mix + budget split): _in / out?_
- **Buying** (execute/adjust campaigns on ad platforms): _in / out — likely out of scope for v1?_
- **Measurement** (ingest real performance data): _in scope as input data, or fully out for v1?_

## 3. What "Agentic" Means Here

This decision drives the architecture, so it needs to be explicit rather than assumed:

- **Interaction model:** single-shot (brief in → one plan out) vs. iterative/conversational (plan, get feedback, re-plan)?
- **Tool use:** does the agent look up external data itself (CPM benchmarks, audience sizing, pacing data), or reason only from what's typed into a form?
- **Autonomy over time:** human-triggered each session, or expected to run/re-optimize on its own over time?

## 4. Differentiation

**Why does this beat a human planner + spreadsheet, or an existing tool** (e.g. Google Performance Planner, The Trade Desk, Skai, MMM vendors)?
_TBD_

**Vertical/channel focus, or general-purpose?**
_TBD_

## 5. Output & Success Criteria

**What does a good output look like?**
_TBD — budget split by channel with rationale? Flight timing? Specific placements? Confidence ranges?_

**How do we know if a plan is actually good?**
_TBD — checked against real outcomes, or judged qualitatively for now?_

## 6. Technical Decisions Log

Decisions made so far, and why — update this as the stack/architecture solidifies:

- **Repo:** `agentic-planner`, local git initialized via GitHub Desktop 2026-09-16. Not yet published to GitHub.com.
- **LLM:** Anthropic Claude, planned. No API key set up yet — v1 build will use mock outputs to avoid API cost until the product shape is validated against this spec.
- **Stack:** not yet chosen — deliberately deferred until scope (Section 2) and agentic behavior (Section 3) are settled, since those determine whether this needs a stateful backend, external tool-calling infrastructure, etc., vs. a simple form-in/plan-out app.

## Changelog

- 2026-09-16: Initial skeleton created from early scoping conversation. All core questions still open.
