# Onboarding prompt

Paste one of these at the start of a session with any AI model to bring it up to speed.

---

## Short version — when the model can read files

```
Read AI_CONTEXT.md in the repo root before doing anything else. It explains what this
project is, what has been built, what has been measured, and the gotchas that cost real
time to discover.

Then read CLAUDE.md for the condensed conventions.

Two rules that matter most here:
1. Never return a confidently wrong answer — declining to guess beats guessing wrong.
2. Measure, don't assume. Score any recognition or detection change with
   backend/scripts/evaluate_detection.py, which replays 101 real scans and fails on a
   single regression.

Tell me what you understand the current state and the best next step to be before you
propose any work.
```

---

## Long version — when the model cannot read files

Paste the entire contents of `AI_CONTEXT.md`, then:

```
That is the current state of my project. Before proposing anything:

- Tell me what you think the highest-value next step is, and why.
- Flag anything in that document that looks wrong, outdated, or internally inconsistent.
- Ask about anything you would need to verify before writing code.

Do not start implementing until we have agreed on the approach.
```

---

## Keeping this current

`AI_CONTEXT.md` is only useful if it is true. Update it whenever any of these change:

- **Architecture** — a new module, a swapped library, a changed data flow
- **Measured results** — new accuracy, coverage, or timing numbers
- **The roadmap** — a phase completed, blocked, or reordered
- **A gotcha** — anything that cost more than an hour to discover

The rule of thumb: *if a fresh AI would make a worse decision without knowing it, it belongs in the
document.* Update the "Last updated" date at the top when you do.
