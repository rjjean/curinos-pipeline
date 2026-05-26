# AI Manifest

Documents how AI tools were used to build this validation pipeline, where AI output was wrong, and how those failures were caught and corrected.

## Tools and how they were used

| Tool | Used for |
|---|---|
| Claude (Anthropic) | Architecture design; initial scaffolding of the FastAPI AUT, Playwright POM, orchestrator, and k6 script; pair-debugging environmental issues; reviewing test edge cases |

## Strategy

I used AI for architecture and scaffolding first, implementation second. The architectural conversation, working through the five-layer separation (AUT, tests by concern, orchestrator, reports, CI), happened before any code was written.

For implementation, three operating rules:

1. **AI output is a draft, never a commit.** Every generated chunk got read line-by-line before being kept. Several were rewritten when I didn't agree with the structure.
2. **AI is unreliable on edge cases and boundary conditions.** Anywhere a test concerned "the unusual case" (empty pages, ties in sort keys, race conditions, cross-language serialization), I wrote the assertion myself and asked AI for review rather than the other way around.
3. **AI cannot test its own code.** Verification that the suite actually catches the bugs it claims to was done by deliberately breaking the AUT and confirming the suite went red. The phase-by-phase failure verification (described in the README) was driven by this principle.

The failures documented below are the most substantive specific instances where AI output was wrong and I caught it. They are not exhaustive,smaller AI errors got caught and corrected continuously throughout development without rising to the level of being worth a manifest entry.

---

## Documented failures

### Failure 1: `is_active` cast was case-sensitive across the JS/Python boundary

**Context.** AI-generated the POM's `_cast` function with `text == "True"` for boolean fields. AI also generated the UI's cell-rendering code using `String(rec[col.key])`. Both look correct line-by-line.

**The defect.** JavaScript's `String(true)` returns the lowercase string `"true"`. Python's `bool.__str__` returns `"True"` capitalized. The two assumptions clashed at the cell-text interface. The Python cast could *never* return True: `"true" == "True"` is always False. Every UI boolean read as False, regardless of the API value.

**How detected.** First end-to-end UI test run. Seven of seven reconciler tests failed. Reading the diff output revealed:

- Only `is_active` mismatched; every other field matched
- The pattern was always `(False, True)`, UI False, API True
- Some rows didn't appear in the failure list, and those were the rows where the API value was naturally False (accidental agreement, not correctness)

The signature "UI always shows the same value regardless of input" pointed to a stuck cast rather than a data bug. Confirmed with `node -e 'console.log(String(true))'` which printed `true` lowercase, while the Python cast expected `True` capitalized.

**Fix.** Changed the cast to `text.lower() == "true"` in `tests/ui/pages/table_page.py`. Defensive normalization across the language boundary. Reran all seven UI tests; all pass.

**Lesson.** When AI generates code that crosses language boundaries (JSON serialization, cross-language string formatting, boolean stringification, datetime formatting), assume the boundary contract is wrong by default and test it explicitly. Boundaries are exactly where AI's pattern-matching fails because each side looks correct in isolation; only the *interface* is the bug.

---

### Failure 2: Empty-string sort parameter was incorrectly tested as invalid input

**Context.** AI generated a parametrized negative test for invalid sort specs as `["", "balance", "balance:sideways", "unknown:asc"]`, expecting all four to return 4xx status.

**The defect.** Empty string is *not* invalid input. FastAPI's `Optional[str]` parameter handling treats `?sort=` (empty value) and a missing `sort` parameter identically, both yield `None` in the handler. The server correctly returns 200 with the default unsorted view. The test asserts 4xx, which is wrong. AI generalized from "malformed sort spec" to "empty sort" without checking whether empty had a defined meaning.

**How detected.** First green-field run of `pytest tests/api`: 14 passed, one failed with `assert 200 in (400, 422)`. The parametrize identifier (`sort=''`) made the failing case obvious immediately.

**Fix.** Two changes in `tests/api/test_api.py`. Removed `""` from the bad-input parametrize list. Added a new explicit positive test (`test_empty_sort_param_is_equivalent_to_no_sort`) that asserts `?sort=` returns 200 with `meta.sort == null`. The contract is now asserted in both directions.

**Lesson.** AI-generated bad-input tests should be reviewed for *plausible-but-valid* inputs, not just for the obvious malformed ones. Negative tests document an assumption about what counts as bad input; if that assumption is wrong, the test enforces the wrong contract.

---

### Failure 3: Python 3.14 venv produced no pip, and AI-generated requirements used incompatible packages

**Context.** Ubuntu 26.04 LTS (which I'm developing on) ships Python 3.14 as the default. AI's setup instructions assumed system Python would be installable-into and that a `python3 -m venv .venv` would produce a fully functional environment. Neither assumption held.

**The defect.** Two distinct issues compounded:

1. The 3.14 venv created by `python3 -m venv .venv` didn't include `pip` inside. Running `pip install` inside the activated venv fell back to system pip from `/usr/bin/pip`, which then hit PEP 668's externally-managed protection because system Python *is* externally managed.

2. The Playwright dependency (greenlet) had no prebuilt wheels for 3.14. Pip fell back to building from source. The build failed against 3.14's reorganized CPython internals (`_PyCFrame`, `_PyInterpreterFrame`, `PyThreadState.cframe` no longer exists). Compiler errors about missing struct members.

**How detected.** The first symptom was PEP 668's "externally-managed-environment" error despite an activated venv. Initial hypothesis (mine) was that an `EXTERNALLY-MANAGED` marker had leaked into the venv. Investigation with `which python` and `which pip` revealed the venv's python was correct but pip was system pip, i.e., venv was incomplete. The second symptom (greenlet build failure) appeared once I worked around the pip issue with `python -m pip` and tried to install dependencies.

**Fix.** Abandoned system Python entirely. Installed `uv` (a Python-version-and-package manager from Astral). Used `uv python install 3.12` and `uv venv .venv --python 3.12` to create a Python 3.12 venv. This solved both issues: the 3.12 venv has working pip, and 3.12 has prebuilt wheels for greenlet and every other dependency. Also brought local environment in line with the CI workflow's `python-version: "3.12"`.

**Lesson.** When AI generates a `requirements.txt`, the implicit Python version it targets is the ecosystem-mature version at training time. The wider Python ecosystem lags 3–9 months behind new Python releases for native-code packages. Bleeding-edge Python versions break dependencies in non-obvious ways. Always check or pin the Python version your dependencies actually support before assuming defaults work. Also: prompt indicators (the `(.venv)` prefix) are not proof of state. `which python` and `which pip` are.

---

### Failure 4: AI-supplied k6 install commands used a stale signing key and an unsupported keyring format

**Context.** AI's k6 installation instructions (lifted from older versions of k6's documentation) imported signing key `77C6C491D6AC1D69` via `gpg --keyserver` and stored it as a gpg keybox (`.gpg`) file at `/usr/share/keyrings/k6-archive-keyring.gpg`.

**The defect.** Two problems, both invisible until `apt update` ran:

1. k6's current repository is signed by key `C780D0BDB1A69C86`, not `77C6C491D6AC1D69`. The fingerprint had rotated since the docs were written. apt's complaint was `NO_PUBKEY C780D0BDB1A69C86`, meaning "I see the repo, but the key you imported doesn't match what it's signed with."

2. Modern apt (on Ubuntu 26.04) rejects gpg keybox-format keyring files. The warning was easy to miss in the noise: `The key(s) in the keyring ... are ignored as the file has an unsupported filetype`. Modern apt requires dearmored binary format.

The combination meant the install repo was added but the key was both wrong *and* in a format apt wouldn't read anyway.

**How detected.** `sudo apt update` after adding the repo failed with both warnings visible. Then `sudo apt install -y k6` failed with "Unable to locate package k6" because apt couldn't trust the repo and had filtered out its packages.

**Fix.** Wiped the keybox-format keyring. Downloaded the current key directly from k6's website with `curl -fsSL https://dl.k6.io/key.gpg`. Piped through `gpg --dearmor` to convert to the binary format modern apt accepts. Wrote the result to the same path. Reused the repo definition unchanged. `apt update` then succeeded; `apt install -y k6` then installed `k6 v2.0.0` cleanly.

**Lesson.** AI install instructions for system packages frequently embed values (key fingerprints, repository paths, key formats) that drift over time. The k6 docs themselves drift; AI training data reflects an older state. Always verify against the upstream project's *current* install docs rather than trusting embedded fingerprints, especially when the project rotates keys.

---

### Failure 5: Setup phase didn't install all runtime dependencies

**Context.** Reading my Makefile critically during final review, I noticed the `setup` target installed Python deps and Playwright Chromium but not k6. Meanwhile the orchestrator handled missing k6 by skipping the load phase with a clear message.

**The defect.** Graceful degradation in the orchestrator masked the setup omission. A reviewer running `make all` on a fresh machine would see three of four phases pass, the load phase would skip with "k6 not installed", and the pipeline would still report "PASS." This nominally satisfies the brief's "single command" requirement but actually delivers only three quarters of the brief's required validation phases.

The CI workflow already had k6 install as an explicit step, which is what made the Makefile gap visible: the workflow knew k6 was needed but the Makefile didn't.

**How detected.** Re-reading the Makefile while doing final review. The question "is the setup phase actually installing everything?" surfaced the discrepancy. Confirmed by `cat .github/workflows/pipeline.yml | grep k6` showing the CI install step.

**Fix.** Split the setup target into `setup-python` and `setup-k6` subtargets. The `setup-k6` target uses `command -v k6` to check whether k6 is present and skips if so. On a fresh machine, it runs the same install commands as the CI workflow. The top-level `setup` depends on both, so `make setup` installs everything.

**Lesson.** Graceful skipping in code is not a substitute for complete setup. A skipped phase isn't a passed phase. If a phase has external dependencies, the setup target must own them, relying on the user to install side-tooling is a way of pretending the dependency doesn't exist. This applies especially to test pipelines, where missing-tool skips silently lower the bar from "fully validated" to "validated where convenient."

---

## What this manifest is and isn't

This file documents real failures. Each failure has a concrete artifact behind it. The lessons are mine, drawn from the actual debugging work, and apply beyond this project.

What it isn't: an exhaustive log of every AI rough edge. Smaller errors - variable names I'd have picked differently, comments I rewrote, structural changes I made because the AI's first pass wasn't quite right, happened continuously and aren't documented individually. The failures above are the substantive ones worth a paragraph each.