"""Open a shortlisted offer's application form in a real browser, fill it, and
either hand you the window or submit it.

Run: uv run python -m cli.apply <shortlist position> [--submit] [--min-confidence 0.7]

Two passes over the form. The keyword table below answers the fields that are
always the same — name, email, phone. Everything else (dropdowns, radio groups,
"why do you want to work here", "years of React") goes to one LLM call that sees
the whole form, the profile and the resume at once. Answers below
--min-confidence are left blank and reported rather than guessed.

Without --submit this stops before Submit and before any consent box, exactly as
before. With --submit it ticks the required consents and submits — it prints
what it is about to do and gives you a few seconds to Ctrl-C.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from playwright.async_api import Locator, Page, async_playwright

from jobsearch.database.session import get_sessionmaker
from jobsearch.services.form_answer import Answer, FieldSpec, answer_fields
from jobsearch.services.match import get_shortlist
from jobsearch.services.pipeline import get_latest_resume, get_or_create_local_user

PROFILE_PATH = Path("profile.json")
# a persistent context keeps ATS logins (Greenhouse, LinkedIn) between runs
BROWSER_PROFILE_DIR = Path(".playwright-profile")
SCREENSHOT_DIR = Path("/tmp")
FIELD_SELECTOR = "input, textarea, select"
MAX_STEPS = 6  # Workday/Greenhouse wizards; a cap so a broken Next never loops forever

# label fragment -> profile.json key. Polish included because half the boards are PL.
FIELD_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (("first name", "given name", "imię", "imie"), "first_name"),
    (("last name", "surname", "family name", "nazwisko"), "last_name"),
    (("full name", "your name", "imię i nazwisko"), "full_name"),
    (("email", "e-mail", "mail"), "email"),
    (("phone", "telefon", "mobile", "tel."), "phone"),
    (("linkedin",), "linkedin"),
    (("github", "gitlab"), "github"),
    (("portfolio", "website", "strona", "personal site"), "website"),
    (("city", "miasto", "location", "lokalizacja", "where are you based"), "city"),
    (("country", "kraj"), "country"),
    (("salary", "wynagrodzenie", "rate", "stawka", "compensation"), "salary"),
    (("notice period", "okres wypowiedzenia", "availability", "start date"), "notice_period"),
    (("years of experience", "lata doświadczenia", "experience"), "years_experience"),
]

CONSENT_HINTS = ("consent", "zgod", "rodo", "gdpr", "privacy", "polityk", "terms", "regulamin")
APPLY_HINTS = ("apply", "aplikuj", "apply now", "złóż aplikację", "zloz aplikacje", "send application")
NEXT_HINTS = ("next", "continue", "dalej", "kontynuuj", "next step", "save and continue")
SUBMIT_HINTS = ("submit", "submit application", "wyślij", "wyslij", "send application", "aplikuj teraz")

# One round-trip instead of four attribute reads per field. Returns every control
# with the text a human would read as its label, keeping the index it has in the
# unfiltered nodeList so Python can address it again with .nth(index).
_SCRAPE_JS = """
(selector) => {
  const text = (node) => (node && node.innerText ? node.innerText.trim().slice(0, 300) : "");
  const labelOf = (el) => {
    const forLabel = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
    const aria = el.getAttribute("aria-labelledby");
    const ariaLabel = aria ? document.getElementById(aria) : null;
    return text(forLabel) || text(ariaLabel) || text(el.closest("label"))
      || el.getAttribute("aria-label") || el.getAttribute("placeholder")
      || (el.getAttribute("name") || el.getAttribute("id") || "").replace(/[_-]/g, " ");
  };
  return [...document.querySelectorAll(selector)].map((el, index) => {
    const style = getComputedStyle(el);
    const visible = el.offsetParent !== null || style.position === "fixed";
    const tag = el.tagName.toLowerCase();
    return {
      index,
      tag,
      type: (el.getAttribute("type") || "text").toLowerCase(),
      name: el.getAttribute("name") || "",
      label: labelOf(el),
      // the option list is the whole point of a dropdown — the model has to pick from it
      options: tag === "select" ? [...el.options].map((o) => o.label.trim()).filter(Boolean) : [],
      required: el.required || el.getAttribute("aria-required") === "true",
      maxLength: el.maxLength > 0 ? el.maxLength : null,
      usable: visible && !el.disabled && !el.readOnly && el.type !== "hidden",
    };
  }).filter((f) => f.usable);
}
"""


def match_field(label: str) -> str | None:
    """Map a form label to a profile key. Longest-pattern-first so that
    'first name' never loses to a bare 'name' rule."""
    text = label.strip().lower()
    if not text:
        return None
    best: tuple[int, str] | None = None
    for fragments, key in FIELD_PATTERNS:
        for fragment in fragments:
            if fragment in text and (best is None or len(fragment) > best[0]):
                best = (len(fragment), key)
    return best[1] if best else None


def is_consent(label: str) -> bool:
    return any(hint in label.lower() for hint in CONSENT_HINTS)


def group_radios(controls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse a radio group into one question with options. Scraped raw, a
    yes/no pair looks like two unrelated fields called 'Yes' and 'No', and the
    model answers both."""
    grouped: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    for control in controls:
        if control["type"] != "radio":
            grouped.append(control)
            continue
        # radios with no name aren't a group — treat each as its own question
        key = control["name"] or f"__{control['index']}"
        group = seen.get(key)
        if group is None:
            # the group's question is the fieldset legend if there is one; the
            # per-radio label is the option text, not the question
            group = {**control, "options": [], "members": {}, "label": control["name"] or control["label"]}
            seen[key] = group
            grouped.append(group)
        option = control["label"] or str(control["index"])
        group["options"].append(option)
        group["members"][option] = control["index"]
    return grouped


def to_spec(control: dict[str, Any]) -> FieldSpec:
    kind = control["tag"] if control["tag"] in {"textarea", "select"} else control["type"]
    return FieldSpec(
        index=control["index"],
        kind=kind if kind in {"text", "textarea", "select", "radio", "checkbox", "number", "date"} else "text",
        label=control["label"],
        options=control.get("options", []),
        required=control["required"],
        max_length=control["maxLength"],
    )


def load_profile() -> dict[str, Any]:
    if not PROFILE_PATH.exists():
        sys.exit(
            f"{PROFILE_PATH} not found. Create it, e.g.:\n"
            '{\n  "first_name": "Lukasz",\n  "last_name": "Wasyleczko",\n'
            '  "email": "you@example.com",\n  "phone": "+48…",\n'
            '  "linkedin": "linkedin.com/in/…",\n  "city": "Warsaw",\n'
            '  "resume_path": "/absolute/path/to/cv.pdf"\n}'
        )
    return json.loads(PROFILE_PATH.read_text())


async def _click_first(page: Page, hints: tuple[str, ...]) -> bool:
    for hint in hints:
        candidate = page.get_by_role("link", name=hint, exact=False).or_(
            page.get_by_role("button", name=hint, exact=False)
        )
        if not await candidate.count():
            continue
        # the click may navigate this tab, open a popup, or just reveal a modal —
        # the caller re-reads context.pages[-1], so all three land in the same place
        await candidate.first.click()
        await page.wait_for_timeout(2500)
        return True
    return False


def _nth(page: Page, index: int) -> Locator:
    return page.locator(FIELD_SELECTOR).nth(index)


async def _set(page: Page, control: dict[str, Any], value: str) -> None:
    """Type/pick `value` into one control, whatever kind it is."""
    field = _nth(page, control["index"])
    if control["tag"] == "select":
        try:
            await field.select_option(label=value)
        except Exception:  # some ATS dropdowns only match on value, not label
            await field.select_option(value)
    elif control["type"] == "radio":
        await _nth(page, control["members"][value]).check()
    elif control["type"] == "checkbox":
        await field.set_checked(value.strip().lower() in {"true", "yes", "tak", "1"})
    else:
        await field.fill(value)


async def _fill_form(
    page: Page, profile: dict[str, Any], resume_text: str, job_text: str, min_confidence: float
) -> dict[str, list[str]]:
    report: dict[str, list[str]] = {"filled": [], "blank": [], "consent": [], "uploaded": [], "reasoned": []}
    controls = group_radios(await page.evaluate(_SCRAPE_JS, FIELD_SELECTOR))

    unresolved: list[dict[str, Any]] = []
    for control in controls:
        label = control["label"]

        if control["type"] == "file":
            resume = profile.get("resume_path")
            if resume and Path(resume).exists():
                await _nth(page, control["index"]).set_input_files(resume)
                report["uploaded"].append(f"{label or 'file'} ← {Path(resume).name}")
            continue

        if is_consent(label):
            # ticking a consent is a knowing act — held back for the submit gate
            report["consent"].append(label)
            continue

        # pass 1: the fields that are the same on every form, no LLM needed
        key = match_field(label) if control["tag"] != "select" and control["type"] != "radio" else None
        value = profile.get(key) if key else None
        if value:
            await _set(page, control, str(value))
            report["filled"].append(f"{label} = {value}")
        else:
            unresolved.append(control)

    # pass 2: everything else, in one call
    by_index = {control["index"]: control for control in unresolved}
    answers: dict[int, Answer] = await answer_fields(
        [to_spec(control) for control in unresolved], profile, resume_text, job_text
    )
    for control in unresolved:
        label = control["label"]
        answer = answers.get(control["index"])
        if answer is None:
            report["blank"].append(f"{label} — no grounded answer")
            continue
        if answer.confidence < min_confidence:
            report["blank"].append(f"{label} — {answer.confidence:.2f} '{answer.value[:60]}' ({answer.reason})")
            continue
        if control.get("options") and answer.value not in control["options"]:
            report["blank"].append(f"{label} — '{answer.value}' is not one of the options")
            continue
        await _set(page, by_index[control["index"]], answer.value)
        report["filled"].append(f"{label} = {answer.value[:80]}")
        report["reasoned"].append(f"{label}: {answer.reason}")

    return report


def _print(report: dict[str, list[str]]) -> None:
    for line in report["filled"] + report["uploaded"]:
        print(f"    ✓ {line}")
    for line in report["blank"]:
        print(f"    ⚠ blank — {line}")
    for line in report["consent"]:
        print(f"    ☐ consent — {line}")


async def _tick_consents(page: Page) -> list[str]:
    ticked = []
    for control in await page.evaluate(_SCRAPE_JS, FIELD_SELECTOR):
        if control["type"] == "checkbox" and control["required"] and is_consent(control["label"]):
            await _nth(page, control["index"]).check()
            ticked.append(control["label"])
    return ticked


async def main(position: int, submit: bool, min_confidence: float) -> None:
    profile = load_profile()

    async with get_sessionmaker()() as session:
        user = await get_or_create_local_user(session)
        resume = await get_latest_resume(session, user.id)
        shortlist = await get_shortlist(session, user.id)

    if resume is None:
        sys.exit("No resume saved. Save one on /profile first — the answers are grounded in it.")
    if not 1 <= position <= len(shortlist):
        sys.exit(f"Shortlist has {len(shortlist)} entries; pick 1-{len(shortlist)}")
    score, summary, title, company, url, *_ = shortlist[position - 1]
    job_text = f"{title} at {company or 'unknown company'}\n{summary}"
    print(f"[{score}] {title} — {company or '?'}\n      {url}\n")

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(BROWSER_PROFILE_DIR), headless=False, viewport={"width": 1400, "height": 1000}
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        await _click_first(page, APPLY_HINTS)
        page = context.pages[-1]

        blanks: list[str] = []
        for step in range(1, MAX_STEPS + 1):
            print(f"form step {step}: {page.url}")
            report = await _fill_form(page, profile, resume.raw_text, job_text, min_confidence)
            _print(report)
            blanks += report["blank"]
            await page.screenshot(path=str(SCREENSHOT_DIR / f"apply-{position}-step{step}.png"), full_page=True)
            if not await _click_first(page, NEXT_HINTS):
                break
            page = context.pages[-1]

        print(f"\nscreenshots: {SCREENSHOT_DIR}/apply-{position}-step*.png")

        if not submit:
            print("Browser is open. Review the form, tick the consents, click Submit yourself.")
        elif blanks:
            print(f"NOT submitting: {len(blanks)} field(s) left blank. Finish them, or lower --min-confidence.")
        else:
            ticked = await _tick_consents(page)
            for label in ticked:
                print(f"    ☑ ticking required consent — {label}")
            print("\nSubmitting in 8s. Ctrl-C to stop.")
            await page.wait_for_timeout(8000)
            print("submitted" if await _click_first(page, SUBMIT_HINTS) else "no Submit button found — over to you")

        await asyncio.get_running_loop().run_in_executor(None, input, "Press Enter here when done… ")
        await context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare (or send) an application from the shortlist.")
    parser.add_argument("position", type=int, help="shortlist position, 1 = best match")
    parser.add_argument("--submit", action="store_true", help="tick required consents and click Submit")
    parser.add_argument("--min-confidence", type=float, default=0.7, help="below this, leave the field blank")
    args = parser.parse_args()
    asyncio.run(main(args.position, args.submit, args.min_confidence))
