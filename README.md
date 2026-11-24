# Agentic Media Planner (prototype)

A prototype of an agent that helps plan a streaming-TV media buy. A planner types a short
request ("build a plan for Summit Ridge, $800K, spring-summer 2027, here's the RFP") and the
system gathers everything relevant, reads it, asks for confirmation, and then produces a plan.

This is a learning project, not a product. Everything in `fixtures/` is made up, and the
plan numbers are placeholders. What is real is the shape of the system and how it is tested.

## The core idea: the model reads, the harness enforces

Media plans have rules that must never be broken: an advertiser's excluded publishers, a
required audience-data provider, committed spend on existing deals. The design rule is:

> The model sees everything relevant, but nothing correctness-critical depends on it.

- **The model** reads the chat message, the RFP (PDF), the advertiser record, commitments and
  brand guidelines, and writes a structured summary of what the planner wants.
- **Plain code** reconciles that summary, composes the rules, and validates the final plan.
  Hard rules are enforced at the tool boundary and by a final validator, never by asking the
  model to comply.
- **Unknown is a warning, not a block.** Missing guidelines or a failed lookup warns the
  planner. Only a plan that breaks a *known* hard rule is blocked.

### Reconciliation

Extraction does not trust a single answer. For each field the model returns **candidates**,
each with its source (chat, RFP, advertiser record) and a verbatim quote. Code then checks
that every quote really appears in its source and classifies the field:

| Status | Meaning |
|---|---|
| settled | sources agree, or only one source speaks |
| conflict | sources disagree (e.g. chat says $800K, RFP says $750K) |
| ambiguous | one source gives several answers for a single-valued field (e.g. several goals) |
| missing | nobody said |

The Verify screen shows conflicts and gaps to the planner instead of silently picking one.

### Rule composition

Rules from different sources combine by restriction, never by loosening:

- publisher exclusions **union**; audience-provider allow-lists **intersect** (empty means blocked)
- guideline rules are hard or soft: hard can never be overridden, soft can, with a warning
- existing commitments are budget **floors**; a commitment on a hard-excluded publisher is a blocker

## What works today

- Three-screen Streamlit UI: **Input** (chat + RFP) → **Verify** (summary, conflicts, brand
  rules) → **Plan** (budget per publisher, reach, frequency, totals).
- Context assembly from a chat message, a PDF, and fake advertiser services that serve
  commitments and compiled guidelines from fixtures, with fault injection for failure cases.
- Structured extraction using the Anthropic Messages API with JSON-schema structured outputs.
- Reconciliation, quote checking, and scoring against expected values.
- Rule composition and a plan validator.
- A dummy deterministic plan generator that honors the composed constraints.
- Export to the buyer: the Plan screen's **Download buyer handoff (JSON)** button writes the
  plan as `plan_handoff.v0` for [agentic-buyer](https://github.com/uws-builder/agentic-buyer). `planner/handoff.py` is
  the only code that knows that format.
- Commit safeguards (see below).

## What is not built yet

- Real planning: the plan is deterministic dummy data. There is no optimizer or catalog yet.
- Mapping restricted publisher names to catalog entries, with user confirmation.
- Commitment floors flowing into the allocation, and the buying-model column in the output.
- Compiling brand-guideline prose into rules at upload time (fixtures stand in for this).
- The extraction step does not yet read commitments or guidelines directly.
- A larger eval set: harness fault injection, tool use, and judged reasoning quality.

## Run it

Needs Python 3.11+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,ui]"
```

```bash
.venv/bin/streamlit run app.py
```

The UI starts in **demo mode**, which uses scripted model output and costs nothing. To use the
real model, copy `.env.example` to `.env`, put your Anthropic API key in it, and switch to real
mode in the UI. `.env` is gitignored. The server binds to localhost only, because real mode
spends your key.

Run the tests (no API key needed):

```bash
.venv/bin/pytest
```

Run the extraction eval against the real model (uses your key):

```bash
.venv/bin/python scripts/run_live_eval.py
```

## Layout

```
app.py                    launcher so Streamlit reloads edits under src/
src/planner/
  ingest/pdf.py           PDF to text (swappable extractor)
  context.py              bundles chat, PDF, advertiser, commitments, guidelines
  schema.py, summarize.py extraction schema, extraction call, reconcile, render
  model.py                model client interface, scripted client, Anthropic client
  rules.py                rule composition and plan validator
  commitments.py, guidelines.py, services.py
                          fake services with fault injection
  plan.py                 dummy plan generator
  handoff.py              export a plan as plan_handoff.v0 for the buyer
  evals.py, cases.py      scoring and case loading
  ui/streamlit_app.py     the three screens
cases/                    eval cases: inputs plus expected values
fixtures/                 made-up advertisers, commitments and guidelines
tests/                    unit, UI (Streamlit AppTest) and safeguard tests
githooks/                 pre-commit and pre-push checks
```

## Design choices worth knowing

- **Raw Messages API, not an agent SDK.** The loop is small and explicit so each step can be
  tested on its own. Backends are swappable behind small interfaces (PDF extractor, model
  client, services).
- **Structured outputs, not forced tool calls.** The extraction schema is enforced through the
  API's JSON-schema output format.
- **Fakes first, evals from day one.** Deterministic fake services stand in for real systems,
  so tests never depend on an LLM to simulate data, and real backends can be swapped in one at
  a time.
- **Streamlit tested with `AppTest`**, so UI flows run in the normal test suite.

## Safeguards

`githooks/` holds a pre-commit hook (blocks secret files, key-shaped text, personal-provider
emails, and non-noreply author addresses) and a pre-push hook (blocks outgoing commits with a
non-noreply author). Turn them on per clone:

```bash
git config core.hooksPath githooks
```

## Notes

Built iteratively with Claude Code as a pairing tool; commit trailers show where.
