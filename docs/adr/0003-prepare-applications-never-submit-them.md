# ADR 0003 — Applications are prepared in a real browser, never submitted

- **Status:** Accepted
- **Date:** 2026-08-12

## Context

The wanted end state was "hand me a link where everything is filled in and I only
click Submit". A URL cannot carry that. Form values live in the page's DOM and its
session; only forms that explicitly support prefill parameters (Google Forms
`entry.NNN=`, some Greenhouse/Lever fields) can be linked to in a filled state, and
the majority of application forms additionally need a session cookie, a CSRF token,
a file upload, and sometimes an account or a captcha.

## Decision

`cli/apply.py` drives a **visible** Chromium via Playwright in a persistent profile
(so ATS logins survive between runs): open the offer, follow the apply control, fill
every field it can match from `profile.json`, attach the CV, screenshot the result,
print a report, and **leave the browser open**. The human reviews the form and
clicks Submit.

Three things it deliberately does not do:

1. **Never clicks Submit.** The last action is always a human's.
2. **Never ticks consent, GDPR/RODO or terms checkboxes.** Those are legal
   declarations; agreeing on someone's behalf is not a convenience. They are listed
   in the report as `☐ your click`.
3. **Never picks a dropdown option or invents free-text answers.** "Seniority",
   "How did you hear about us", "Why do you want to join us" are reported blank
   rather than guessed.

Field matching is a label→profile-key table (English and Polish, since half the
boards are PL), longest fragment wins, driven off `aria-label` / `placeholder` /
`name` / `id`.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Prefilled URLs | Only works on a minority of forms. Verified against the current shortlist: most entries route to ATSes with no prefill support at all. |
| Headless submit-it-all | Mass automated submission is what site ToS actually prohibit, it is unreviewable, and one bad extraction emails a wrong salary expectation to a real employer. |
| Per-ATS adapters (Greenhouse, Lever, Ashby…) | A generic label matcher already fills the standard six fields on any of them. Adapters are worth writing when a specific ATS is observed to break, not before. |
| HTTP POST straight to the form endpoint | Fails on CSRF, multipart CV upload and bot protection, and produces no reviewable state. |

## Consequences

- Requires a desktop session — the browser is visible by design, so this step cannot
  run in the weekly cron. Ingest, retrieval and scoring are unattended; applying is not.
- `profile.json` holds personal data and lives outside git (`.gitignore`), as does
  `.playwright-profile`, which contains real session cookies.
- Free-text answers are the obvious next step: they can be drafted per posting from
  the retrieved resume sections, which is the same context the scorer already builds.
- Verified against a synthetic form covering both languages, a file input, a select,
  a consent checkbox and a hidden CSRF field: six fields filled, CV attached,
  free-text and dropdown reported blank, consent left for the human.
