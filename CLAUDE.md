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
- **Never pass `temperature` to `client.messages.create`.** The models used in this project
  reject it with `Error code: 400 — temperature is deprecated for this model`; a static test in
  `tests/test_pipeline.py` (`test_no_temperature_param`) fails the suite if it reappears.

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
- `src/decisions.py` (Issue #583, stage 1 only) — a cumulative log (`state/decisions.json`) of
  every draft's eventual fate: `published` (hooked into `publish.py:publish_one`, both the photo
  and reel branches), `rejected_explicit` (hooked into `collect_feedback.py`, the existing
  `/reject` path), and two signals inferred from behavior that already exists with no new
  write at collection time — `dismissed_closed` (the review Issue closed with a given draft still
  unapproved — explicit, since `review.build_issue_body` already tells the reviewer "closing the
  Issue = dismiss all") and `ignored_timeout` (the Issue stayed open past
  `config.yaml: decisions.ignore_timeout_hours` with no action at all — inferred, not observed).
  `decisions.scan()` (called unconditionally near the top of `collect.py:main`, wrapped in
  `try/except` so an auxiliary data-collection step can never fail a real collection run) computes
  the two inferred signals once per run, independent of whether that run produces any new drafts,
  because an Issue can cross into "closed" or "timed out" between runs with no other event to
  trigger the check. Collection only — no analysis, no scoring, no feedback into ranking or
  screening. **Binding constraint on any future work in this direction:** if this ever moves from
  "surface a report" to "influence something", the effect must be a rank demotion, never an
  exclusion — the same principle already applied to `verify.demoted_readers` above. The reasoning,
  from the review discussion that scoped stage 1: a system that pre-filters toward what it predicts
  a reviewer will approve narrows their coverage instead of improving it, and a small sample of
  decisions locks in a bias rather than revealing a real pattern — the existing `≥3` repetition
  floor in `feedback.screening_guidance`/`summarise` is the model to follow, not a one-off count.
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

**Known limitation, not yet addressed (Issue #373):** in `src/evidence.py`'s read-candidate
ranking (`_candidate_score` = `_read_priority` + `_relevance`), when relevance ties at zero for
every remaining candidate — common once real coverage of an event is thin — the tie is broken by
Python's stable sort, i.e. by whatever order the candidates arrived in from ranking/clustering
upstream, which has no relationship to the current claim. There is no real "choice" happening at
that point, just inherited order. Deliberately left alone for now (see the issue for prior
diagnosis of two related fixes — a relative rather than absolute `READ_DEMOTION_PENALTY`, and
`loose_relevance` for the support-evidence round — both deferred to avoid another regression
cycle in this area).

**Addressed (Issue #373) — a second, distinct failure mode in the same ranking, not the zero-tie
case above:** a real run (`روبيرتو كارلوس`/Roberto Carlos Islam story) showed a generic, unweighted
publisher outrank a trusted wire agency in `_candidate_score` even though relevance was *not* tied
at zero — the generic candidate's title happened to share several literal words with the query
(`_relevance` had no upper bound), which was enough to close the fixed 2.4-point gap between
`DEFAULT_PUBLISHER_WEIGHT` and `TRUSTED_PUBLISHER_WEIGHT`. Same failure shape as the original
365Scores sample at the top of this issue (a weak-authority source winning on a literal match), but
happening one layer later — in the composite read-priority score itself, not in the `relevant()`
pre-filter that was already relaxed for it. Diagnosed with real numbers first, not inference: the
`top_candidates` logging added to settle this (see below) recorded an actual production case — a
default-weight candidate (weight 0.6, relevance 4) outscoring a trusted one (weight 3.0, relevance
1) at 4.6 vs 4.0. Fixed by capping `_relevance`'s contribution to the composite score at
`RELEVANCE_CAP = 3.0` (a value in the valid window `(2.4, 3.4]` derived from *both* this witness and
the original Issue #132 witness it must not regress — a trusted-but-irrelevant source must still
not exclude a highly-relevant default-weight one from the read window), and breaking exact
composite-score ties by weight first instead of inherited arrival order
(`evidence._candidate_sort_key`). `top_candidates` (name/weight/relevance/composite score, still
logged to `trail` and rendered in the article report) remains the tool for settling any future
dispute in this area with real numbers before touching `_candidate_score` again.

**Known limitation, not yet addressed (Issue #373):** foreign personal/place names transliterated
into Arabic often have more than one accepted spelling (e.g. "روبرتو"/"روبيرتو" for "Roberto"), and
nothing in the pipeline normalizes across them. This isn't confined to
`verify_draft.check_originality`'s literal n-gram matching (where a one-word spelling difference
silently defeats a match) — the same gap can weaken `evidence._relevance` and `article._support_sources`
for any claim about a foreign public figure, since both also key off literal word matches. No fix
yet; flagged here so it isn't rediscovered as a fresh bug the next time a foreign-name story hits
this issue.

**Known limitation, not yet addressed (Issue #373):** a brief written in a third language (neither
Arabic nor the source coverage's language) breaks entity-based search, because `entities` are
extracted verbatim in whatever script the brief uses
(`article.WRITEUP_EXTRACT_SYSTEM`/`WRITEUP_EXTRACT_SCHEMA`, "كما وردت في الموجز حرفيًا بلا أي إعادة
صياغة" — no language exception exists) and `evidence.build_query`/`build_query_for_claim` build the
search query straight from that literal text. A real run with a Turkish-language brief produced
`[تصريح] Feysal bin Farhan ABD Trump` as a query. `request.relevant()` already splits wanted tokens
into `q_ar`/`q_latin` and matches each only against articles of the matching script (Arabic-script
vs. everything else) — but that split is binary, not per-language: Turkish is Latin-script, so its
tokens landed in `q_latin` and cross-matched *any* non-Arabic-script article in *any* language
(Japanese, Iranian, SANA all matched) on generic overlap like "Trump", while genuine Arabic-language
coverage of the actual story was never reached because `q_ar` stayed empty (no Arabic characters in
the query at all). Net effect: 16 "matched" results, all noise, zero real support — same shape as
the earlier foreign-name-spelling gap above, but at the language level instead of the transliteration
level. **This witness is also the case worth keeping regardless of the language bug:** the pipeline
abstained instead of drafting an unsupported claim about a named foreign minister quoting Trump — a
claim of that weight, if real, would have led the wire agencies, and it hadn't. That's the intended
line between "we didn't find it" (a pipeline gap, like this one) and "it doesn't exist" (a correct
refusal) — the abstention was right even though the search behind it was broken for the wrong
reason. No fix yet.

**Known limitation, not yet addressed (Issue #373):** `request._AR_STOP` entries written with alef
maksura (e.g. `"على"`) never actually match inside `request.norm_tokens`, because the word is
compared against the stop set *after* `_AR_TRANS` translation (`ى`→`ي`, so `"على"` becomes
`"علي"` before the membership check, and the untranslated `"على"` in the set is never hit).
Discovered while building `article._unsourced_entities` (review request, Issue #373, round 17,
item 2-c), where it leaked `"على"` through as a bogus "content word" and produced a false-positive
report line. Fixed locally there only (`article._AR_STOP_NORM`, a pre-translated copy of the stop
set used just by `article._content_words`) — deliberately **not** fixed in `request.norm_tokens`
itself, following this issue's repeated caution about touching shared normalization functions for a
narrow fix (see the `require_relevance`/`loose_relevance` scoping decision above): `norm_tokens` is
consumed by relevance scoring, query building, and `verify_draft.check_originality` across the whole
project, and a behavior change there needs its own dedicated diagnosis and regression fixtures, not
a side effect of an unrelated feature. Flagged here so it isn't rediscovered as a fresh bug.

**Addressed (Issue #373), partially — a third foreign-language-brief witness, different failure
shape from the two above:** a Turkish-language brief (a Bayraktar quote) had `extract_brief`
translate the *statement text* into Arabic while `entities` stayed literal Turkish — so this time
`evidence.build_query_for_claim` actually found the right documents (Daily Sabah, Yeni Şafak,
Haberler.com, seven results). The failure moved one stage downstream: `_support_sources`/
`_ask_answer_model`/`_ask_naming_model` then judged an Arabic claim/question against Turkish/
English document text and found "no support," because none of their system prompts told the model
that a language mismatch was expected rather than evidence of no match — a plain content judgment
across languages should have worked, the prompt just never said it was normal. Fixed by a shared
`LANGUAGE_NOTE` constant appended to `SUPPORT_SYSTEM`, `STATEMENT_SUPPORT_SYSTEM`,
`REPORT_SUPPORT_SYSTEM`, `ANSWER_SYSTEM`, and `NAMING_SYSTEM` (`src/article.py`) — cheaper and less
brittle than translating every claim/document pair before every judgment call, since the model
already understands both languages. `verify_draft.check_originality` was deliberately left
untouched (literal n-gram matching breaks across languages by construction — dormant here, not a
gap) and so was `DRAFT_SYSTEM_TEMPLATE` (the final post is always written in Arabic regardless of
source-document language, so no extra instruction was needed there).

**Known limitation, not yet addressed (Issue #373):** the consistency gate (`_naming_consistent`)
still cannot accept a naming candidate when the vague reference's `proper_nouns` are Arabic and
every naming-candidate document is in a non-Arabic language — its entity check is literal
`norm_tokens` set intersection, which can never match across scripts, so the gate rejects even when
the event was correctly named from the right documents. Deliberately not fixed: the gate's
entity/date logic shares `norm_tokens`/`_extract_dates` with the rest of the project, and this issue
has repeatedly paid in extra diagnosis rounds for touching those functions for a narrow fix. What
*was* done instead: `article._naming_language_mismatch` (diagnostic only — computed alongside the
gate's decision, never feeds into it) detects this specific case, and the rejection message written
to `trail`/the report now names it explicitly ("الوثائق بلغة غير عربية فلم يقع تطابق الكيانات
حرفيًا") instead of the generic "doesn't mention the entities" message — so a language-mismatch
rejection here isn't mistaken for a search failure and re-diagnosed from scratch next time.

**Added (Issue #373), enabled after a live run surfaced and fixed two design bugs:**
`src/article.py` can extract facts from the independently-read source documents themselves, not
only from the pasted brief (`article._extract_source_facts`, `SOURCE_EXTRACT_SYSTEM`) — a brief
written by a human necessarily omits information the sources actually contain. Every extracted fact
is checked against the already-grounded brief facts by a dedicated semantic-duplicate judgment
(`article._source_fact_duplicate_index`, `SOURCE_FACT_DEDUP_SYSTEM`) before anything else happens
to it — comparing the *event*, not shared entities (one person can be party to two unrelated
events; sharing entities must not merge them) — because a failure here silently double-counts a
fact and lets an article clear `min_grounded_facts` on padding rather than real content.

The first live run (9 facts extracted) showed the original design was wrong on how a surviving fact
gets grounded: it ran a *fresh* `evidence.search`/`gather_evidence` cycle from the fact's own
entities — the same narrow-query trap diagnosed earlier in this issue for unnamed-event naming — and
6 of 9 facts came back `0 raw ← 0 matched`, even though the fact was extracted from a document
already sitting in `all_read_docs`. Fixed: a surviving fact is now grounded directly against the
already-read corpus (`article._dedup_docs_by_publisher` — publisher-identity-deduped, keeping the
longest text per canonical name — feeding `article._support_sources` with no search in between);
"two independent sources" means two independent documents from `all_read_docs`, not a fresh web
result that may not exist yet. `article._rank_docs_for_source_extract` (weight-then-relevance
ordering, reusing `evidence._candidate_score`/`_candidate_sort_key`, same principle as
read-candidate selection) still caps and ranks what's shown to the *extraction* prompt
(`article.source_extract_max_docs`) — that cap no longer also limits the *grounding* corpus, which
sees the full deduped `all_read_docs` so a real independent corroboration already sitting in the
run isn't lost just because it didn't rank into the extraction prompt.

The same run showed a second, distinct bug: extraction went off-topic (`SOURCE_EXTRACT_SYSTEM` had
only a soft "relevant to the topic" instruction) — a document about top taxpayers that happened to
mention the brief's company in passing yielded facts about *other* companies in that same article,
which are not about the brief's topic just because they share a read document with something that
is. Fixed with both a tightened prompt (explicit instruction + the taxpayer-article example) and a
structural post-extraction filter (`article._write_article`'s source-fact loop): a candidate fact's
`entities` must share at least one token with the brief's own topic/entities before it's even
considered for dedup or grounding — cheap, runs before any model call, and is not a linguistic
classifier (unlike the "تعريف/خبر" criterion rejected twice elsewhere in this issue) since it's a
plain token-intersection check. Off-topic exclusions are reported in `trail`, not silently dropped,
and counted in `source_facts_summary["off_topic"]`.

`SOURCE_EXTRACT_SYSTEM` mandates Arabic for both `text` and `entities` even when the source
documents are in another language — unlike the brief's own entity extraction, which deliberately
keeps the brief's original script, here the source is foreign and the article is always Arabic, so
an entity in the source's alphabet would never match a later Arabic search. Every run's report shows
the extraction/merge/off-topic/add counts and a dedicated "wasn't in my brief" section listing what
got added, on the standing lesson (`judged_by`) that a feature with no visible trail effect is a
feature nobody can tell is working. `config.yaml: article.source_extract_enabled` was flipped to
`true` once the first live run's findings above were fixed, same operational precedent as
`article.include_opinion`.

## Testing

`tests/test_pipeline.py` is the entire test suite — no pytest, no separate test files. It fakes
all network calls and the Claude API (`install_fakes()`), so the full run is free and hits
nothing external. It covers ranking/clustering, dedupe memory, Arabic shaping/line-wrapping, the
full collect pipeline end-to-end, and the review round-trip. When adding a feature, add a
`test_*()` function (or extend an existing one) and call it from `main()`; use the existing
`check(name, condition, detail)` helper rather than `assert`.
