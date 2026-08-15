# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An Arabic-language news bot: pulls trending world news from ~90 RSS feeds, dedupes/ranks/clusters
it, drafts an Arabic post via the Claude API, builds a branded image card, and stages everything
in `drafts/` behind a GitHub Issue for human review before publishing to a Facebook Page via the
Graph API. Runs entirely on free GitHub Actions — no server, no paid hosting. See `README.md`
(in Arabic) for the full setup/operations guide; it is the source of truth for user-facing
behavior and should stay in sync with any workflow changes.

## Commands

```bash
pip install -r requirements.txt
bash scripts/fetch_fonts.sh          # only needed to refresh embedded fonts

python -m src.collect --limit 2      # generate 2 draft posts locally
python -m src.publish --verify       # check the Facebook token without posting
python -m src.publish --all-pending  # publish everything pending (real publish — careful)

python -m tests.test_pipeline        # run the full test suite
```

There is no separate test runner/framework (no pytest) and no linter configured — the project's
only quality gate is `tests/test_pipeline.py`, run directly as a module.

## Project-specific conventions (mandatory)

These are enforced by convention, not tooling, so hold to them deliberately:

- **Comments are written in Arabic**, and every comment explains *why* a decision was made, not
  what the line does (the code already says what). Look at any existing file — e.g.
  `src/collect.py` or `config.yaml` — for the expected style: short, reasoning-focused notes
  attached to non-obvious choices (thresholds, ordering constraints, workarounds).
- **Every code change must be paired with an update to `tests/test_pipeline.py`.** This is the
  only test file in the project (see Testing below) — add or adjust a `check(...)` assertion
  for any new behavior, and update fakes/fixtures if you change a function's signature or
  contract.
- **Tests are run with `python -m tests.test_pipeline`** — not `pytest`, not `python
  tests/test_pipeline.py` directly (it relies on being invoked as a module so `sys.path`/imports
  resolve from the repo root).
- **All tunable behavior lives in `config.yaml`, never hardcoded in `src/`.** Thresholds, model
  names, quotas, feature toggles, timing/scheduling parameters, source lists — all belong in
  `config.yaml` and are read via `Config.path("a.b.c")` (`src/config.py`). If you find yourself
  adding a magic number or a new source to a `.py` file, it almost certainly belongs in the
  config instead.

## Architecture

**Two independent pipelines, connected by files in `drafts/` and a GitHub Issue:**

1. **Collect** (`src/collect.py`, triggered via `.github/workflows/collect.yml`'s
   `workflow_dispatch`; `collect.yml` has no GitHub `schedule:` cron — GitHub's free scheduler
   was unreliably dropping runs, so an external cron-job.org job calls `workflow_dispatch`
   several times a day instead):
   fetch RSS (`src/sources.py`) → dedupe/cluster near-identical stories via Jaccard title
   similarity and rank by a trend score (`src/rank.py`) → filter against publish history
   (`src/store.py`, N-day memory) → cheap Haiku pre-screen to drop non-viable candidates before
   any expensive step (`src/screen.py`) → optional cross-language semantic merge so the same
   event reported in different languages clusters together (`src/merge.py`) → optional
   multi-source article text extraction for grounding (`src/extract.py`) → Arabic drafting via
   Claude (`src/writer.py`) → image card composition (`src/imaging.py`) → write JSON + JPG to
   `drafts/<date>/` and open/refresh a review Issue (`src/review.py`, `src/open_review.py`).
2. **Publish** (`src/publish.py`, triggered by the Issue's `approved` label via
   `.github/workflows/publish.yml`): reads which drafts were checked off in the Issue body
   (`src/review.py`), schedules posting times (`src/schedule.py` — staggers posts, avoids
   perfectly regular intervals on purpose since Facebook penalizes obviously-automated
   cadences), posts via Graph API (`src/facebook.py`), comments with the source link, and closes
   the Issue.

Supporting pieces, each independently triggerable as its own workflow:
- `src/radar.py` — a cheap (no-LLM) check every 15 minutes for breaking news; only calls the
  model and drafts a post when a story crosses velocity/score/source-count thresholds
  (`config.yaml: radar`), and can auto-publish without review if strict thresholds are met.
- `src/request.py` — on-demand "write about X" flow: user supplies keywords (via workflow input
  or an Issue tagged `طلب`), bot searches Google News RSS in Arabic + English and drafts from
  the best match.
- `src/setimage.py` — lets a reviewer swap a draft's image post-hoc via a checkbox/comment
  command in the review Issue, without re-invoking the writer (no model cost).
- `src/feedback.py` / `src/collect_feedback.py` — learns from rejected drafts in the review
  Issue and feeds recent rejection reasons back into `src/screen.py`'s prompt.
- `src/insights.py` — pulls Facebook post performance and derives config-tuning recommendations
  (e.g., "raise `trends.weight`").
- `src/trends.py` — Google Trends signal (what audiences are searching, independent of what
  agencies are publishing).
- `src/velocity.py` — tracks how fast a story is gaining source coverage over time; feeds into
  ranking as the primary "is this actually breaking" signal.
- `src/vision.py` / `src/imagesearch.py` — image quality checks and fallback stock image search
  (Wikimedia/Openverse only — never Google Images, for copyright/detection reasons) when a
  publisher doesn't supply a usable photo.
- `src/reel.py` — builds a vertical video (ffmpeg, local, no external service) from the same
  image + headline as an alternate post format.
- `src/evidence.py` — shared search-and-read engine (query building, `search`, `gather_evidence`,
  publisher-weight/name matching) extracted from `src/verify.py` (Issue #348) because it's generic
  — no judgment/classification logic — and is consumed directly by both `src/verify.py` and
  `src/article.py` below. `src/verify.py` imports from it rather than redefining it.
- `src/article.py` — "article from sources" flow (Issue #348, replaces `src/verify.py` below; the
  two coexist in this PR only until the new path is proven on a real brief — see that issue for
  the removal plan): triggered by an Issue tagged `مقال`. Unlike `verify.py`, the pasted text is
  an **editorial brief** (the poster's idea + information + opinion), not an article to fact-check
  — the output is a new sourced article answering a question, not a verdict table. Pipeline:
  extract the brief into fact/opinion statements (`extract_brief`) → for any fact that alludes to
  an event without naming it, run a widening search ladder (`_name_event`) that names the event
  from search results themselves, never model prior knowledge — entities → unrestricted reference
  search on the entities (context, e.g. a country name, discovered only from those results' text)
  → date+context queries built from that discovered context → widen to remaining entities → for
  every fact (originally named or freshly named), require 2+ independent supporting sources
  (`config.yaml: article.min_confirm_sources`) or it's dropped and reported, never silently
  dropped → **only then**, from the sources-filtered set, gate on a purely numeric sufficiency
  threshold (`article.min_grounded_facts`) and pick the question-headline
  (`_sufficiency`/`_choose_question`) → draft with its own prompt (`DRAFT_SYSTEM_TEMPLATE`, never
  `writer.SYSTEM_PROMPT` — a deliberately separate editorial policy) that also folds the poster's
  opinion in, paraphrased and attributed (`config.yaml: article.opinion_attribution_phrase`), never
  copied verbatim → `verify_draft.check_originality` (reused as-is) rejects literal overlap with
  the brief or sources → image via `verify_draft._image_candidates`/`imagesearch.find_images`
  (same Wikimedia/Openverse-only fallback) → draft through the same `store.save_draft` →
  `drafts/<date>/` → review Issue → `approved` path, tagged `origin: "article"`. Deliberately does
  **not** reuse `verify.classify_fact`/`verify.judge_fact` or its verdict table — those encode the
  exact flaw this path exists to fix (judging the brief's own phrasing instead of what the search
  actually finds); `_support_sources`/`_sufficiency` are new, narrower, purely-count-based
  replacements. See the ordering constraint below before changing the grounding/question-selection
  order.
- `src/verify.py` — fact-check flow for a pasted article (Issue tagged `تحقق`): extracts its
  claims, classifies each (fact/opinion/prediction), searches independent sources for every fact,
  judges each as confirmed (2+ independent sources) / near-confirmed (one strong source) / single
  source / no source / contradicted, and posts a report comment. The pasted article is treated as
  inspiration only, never as a source of information — every judgment comes from independently
  searched sources, never the article's own text or the model's prior knowledge.
- `src/verify_draft.py` — stage 2 of the verify flow, run after `src/verify.py`'s report: if the
  confirmed facts alone are sufficient for a standalone story (central fact confirmed + a
  configurable minimum count, `config.yaml: verify_draft`), drafts a post from the confirmed facts
  and their supporting sources' excerpts **only** — the drafting function's signature never
  accepts the pasted article's text, so it structurally cannot leak into the post (not just a
  convention enforced by review). Reuses `writer.SYSTEM_PROMPT` verbatim (same editorial policy as
  the main pipeline) and the same network-call/retry/JSON-parsing machinery, extracted into
  `writer._call_model`/`writer._post_from_data` so both paths share one implementation — but not
  `writer.write_arabic` itself, since that function's prompt is built from an `Article` (title,
  link, publisher of the *pasted* source), which is exactly what rule 1 forbids passing in here.
  A post-hoc literal-match check rejects the draft (no retry) if it shares a long word run with
  the pasted article or with a source excerpt — attributed quotes verified against a confirmed
  excerpt are exempted. Produces a draft through the exact same path as `collect.py`
  (`store.save_draft` → `drafts/<date>/` → review Issue → `approved` label), tagged with
  `origin: "verify"` for traceability only (no special treatment in review parsing). Triggered by
  `.github/workflows/verify.yml` (`issues: labeled` with label `تحقق`), which needs
  `contents: write` for this stage's draft/image commit and explicitly re-checks the labeling
  actor's repo permission (defense in depth beyond GitHub's own label-permission gate). Before
  spending any model/image cost, `verify_draft.attempt()` also requires the workflow to have
  declared `VERIFY_DRAFT_WRITE_ENABLED=true` in its env — a self-declared, dependency-free guard
  against the workflow file silently drifting out of sync with the code (e.g. a merge that lands
  this module without the matching `verify.yml` update, which would otherwise draft content that's
  quietly discarded because no step exists to commit it).

**Everything is driven by `config.yaml`** (see Project-specific conventions above); `src/config.py`
loads it into a dict subclass with dotted-path lookup.

**Two non-obvious ordering/behavioral constraints worth knowing before touching related code**
(both called out in `README.md`, both encoded as regression tests in `tests/test_pipeline.py`):
- Arabic line-wrapping for the image card must happen on the *logical* string **before**
  reshaping/bidi processing (`arabic-reshaper` + `python-bidi`), or words break mid-glyph.
- In the collect workflow, images must be committed/pushed to the repo **before** the review
  Issue is opened, or the `raw.githubusercontent.com` preview links 404 (the file doesn't exist
  at that URL yet).
- In `src/article.py`, source-filtering must happen **before** question selection, never after.
  `_write_article` filters every extracted fact down to `grounded` (2+ independent sources) first,
  then calls `_sufficiency(grounded, ...)` and `_choose_question(grounded, ...)` — both see only
  the already-sourced set, never the full extracted list. If a question were chosen first and
  facts filtered afterward, the chosen "central" fact could be one that never actually passed the
  sourcing bar — it would look central because it was *picked*, not because it was *checked*. A
  single weakly-sourced fact can never become central by construction, not by a later check.

## Testing

`tests/test_pipeline.py` is the entire test suite — no pytest, no separate test files. It fakes
all network calls and the Claude API (`install_fakes()`), so the full run is free and hits
nothing external. It covers ranking/clustering, dedupe memory, Arabic shaping/line-wrapping, the
full collect pipeline end-to-end, and the review round-trip. When adding a feature, add a
`test_*()` function (or extend an existing one) and call it from `main()`; use the existing
`check(name, condition, detail)` helper rather than `assert`.
