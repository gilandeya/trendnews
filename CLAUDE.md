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

1. **Collect** (`src/collect.py`, scheduled every 6h via `.github/workflows/collect.yml`):
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

**Everything is driven by `config.yaml`** (see Project-specific conventions above); `src/config.py`
loads it into a dict subclass with dotted-path lookup.

**Two non-obvious ordering/behavioral constraints worth knowing before touching related code**
(both called out in `README.md`, both encoded as regression tests in `tests/test_pipeline.py`):
- Arabic line-wrapping for the image card must happen on the *logical* string **before**
  reshaping/bidi processing (`arabic-reshaper` + `python-bidi`), or words break mid-glyph.
- In the collect workflow, images must be committed/pushed to the repo **before** the review
  Issue is opened, or the `raw.githubusercontent.com` preview links 404 (the file doesn't exist
  at that URL yet).

## Testing

`tests/test_pipeline.py` is the entire test suite — no pytest, no separate test files. It fakes
all network calls and the Claude API (`install_fakes()`), so the full run is free and hits
nothing external. It covers ranking/clustering, dedupe memory, Arabic shaping/line-wrapping, the
full collect pipeline end-to-end, and the review round-trip. When adding a feature, add a
`test_*()` function (or extend an existing one) and call it from `main()`; use the existing
`check(name, condition, detail)` helper rather than `assert`.
