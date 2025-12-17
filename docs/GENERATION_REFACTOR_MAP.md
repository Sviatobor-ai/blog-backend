# Article Generation & Enhancement Map

This document inventories the current modules, entry points, and supporting flows that create, publish, retrieve, and post-process articles in the joga.yoga backend. It focuses on existing behavior to inform a later refactor without changing functionality.

## A) Current endpoints and entry points

### Public FastAPI routes (`app/main.py`)
- `POST /artykuly` → `GeneratedArticleService.generate_and_publish` (canonical orchestration shared with admin + queue) →
  - With `video_url`: fetch transcript via `get_supadata_client` and `get_transcript_generator`, then `generate_article_from_raw` (transcript assistant) → `document_from_post` (shared publication helper) for response.
  - Without `video_url`: `OpenAIAssistantArticleGenerator.generate_article` → `ArticleDocument.model_validate` → `prepare_document_for_publication` → `persist_article_document`.
- `GET /artykuly` → `list_articles` → query `Post` ORM for pagination and build `ArticleSummary` objects.
- `GET /artykuly/{slug}` → `get_article` → load `Post`, fallback to `document_from_post` (shared publication helper) to hydrate missing fields.
- `GET /rubrics` → `list_rubrics` → query active `Rubric` entries.
- Legacy duplicates (`include_in_schema=False`): `list_posts_legacy`, `get_post_legacy` wrap the same handlers.

### Admin JSON API (`app/routers/admin_api.py`)
- `POST /admin/search` → `search_videos` proxies SupaData search for candidate videos.
- `POST /admin/queue/plan` → `plan_queue` inserts pending `GenJob` rows for provided URLs.
- `GET /admin/status` → `admin_status` aggregates job counts and runner state.
- `GET /admin/queue` → `admin_queue` returns latest `GenJob` snapshot.
- Runner controls: `POST /admin/run/start`, `POST /admin/run/stop` toggle the background worker (`GenRunner`), which maps queued payloads with `build_request_from_payload` and calls `GeneratedArticleService.generate_and_publish`.
- `POST /admin/generate_now` → `generate_now` executes the transcript→article pipeline synchronously via `process_url_once`, which maps payloads to the HTTP request model and calls `GeneratedArticleService.generate_and_publish`.

### Admin HTML (`app/routers/admin_page.py`)
- `/admin` login form, `/admin/login` token validation, `/admin/dashboard` static handoff to frontend console (no generation logic).

### CLI entry
- `python -m app.enhancer.run_batch` (or `app/enhancer/run_batch.py:main`) to batch-enhance posts via `ArticleEnhancer`.

## B) Current deep research / Parallel integration points

- Implementation: `ParallelDeepSearchClient` in `app/enhancer/deep_search.py`.
- Usage:
  - `ArticleEnhancer` pipeline (`app/enhancer/pipeline.py`) calls `search_client.search` before invoking the writer.
  - Batch CLI (`app/enhancer/run_batch.py`) instantiates the client with `get_parallel_search_settings` and passes it to `ArticleEnhancer`.
  - Tests (`tests/test_enhancer_deep_search.py`, `tests/test_enhancer_run_batch.py`) cover parsing and wiring.
- Call pattern:
  1. `_build_prompt(title, lead)` crafts a Polish research brief.
  2. `_create_task_run` posts to `{base_url}/v1/tasks/runs` (headers include `x-api-key`).
  3. `_poll_run` loops on `/v1/tasks/runs/{run_id}` until a terminal state or timeout.
  4. `_fetch_results` pulls results from provided `result_url` or default `/v1/tasks/runs/{run_id}/result`, optionally adding `expand=output,basis` for first-party hosts.
  5. `_parse_result` normalizes the payload to `DeepSearchResult(summary, sources)`; `_extract_sources` and `_build_source` pick up to five HTTP/HTTPS links while filtering `.ru`/`.su` domains.

## C) Current OpenAI writer integration points

- Article generation assistants (structured drafts):
  - Implemented in `OpenAIAssistantArticleGenerator` and `OpenAIAssistantFromTranscriptGenerator` (`app/services/__init__.py`).
  - Prompt builders now live in `app/services/prompt_builders.py` (topic vs transcript briefs + shared system instructions).
  - Execution: `_execute` uses `OpenAIClient` (`app/integrations/openai_client.py`) to create a thread, add user message, run the assistant, poll for completion, then parse the latest assistant message.
  - Schema validation: `_load_payload` extracts JSON from the assistant reply; `validate_article_payload` validates against `ARTICLE_DOCUMENT_SCHEMA`; `ArticleDocument.model_validate` is used when the HTTP route or transcript pipeline re-validates the returned dict.
- Enhancement writer (adds sections/FAQ):
  - Implemented in `EnhancementWriter` (`app/enhancer/writer.py`), using `openai.OpenAI` chat completions with `_build_system_prompt` and `_build_user_prompt` fed by research insights and current article context.
  - Response parsing: `_extract_text` finds the assistant’s text; `_parse_payload` enforces `added_sections` + `added_faq` and strips code fences.

## D) Current publication/persistence flow

- Normalization before save: `prepare_document_for_publication` (`app/services/article_publication.py`) slugifies using `slugify_pl` + `ensure_unique_slug`, trims title-like fields to ≤60 characters, fills taxonomy section from rubric, sets `seo.slug` and `seo.canonical` (via `build_canonical_for_slug` or override).
- Body rendering: `compose_body_mdx` (`app/services/article_utils.py`) turns section dictionaries into MDX string for storage.
- Persistence: `persist_article_document` writes `Post` with canonical SEO fields, narrative, `faq`, `citations`, and the full `payload`; timestamps `created_at` and `updated_at` default to `datetime.now(timezone.utc)` (overriding DB defaults for new rows).
- Fallback document builder: `document_from_post` (`app/services/article_publication.py`) rehydrates `ArticleDocument` from stored payload or columns, applying normalization helpers for missing data (sections, citations, tags, FAQ, canonical).

## E) Current enhancement/enrichment flow

- Selection: `select_articles_for_enhancement` (`app/enhancer/selection.py`) picks posts with `updated_at` ≤ now − 15 days and a non-null payload.
- Orchestration: `ArticleEnhancer.enhance_post` (`app/enhancer/pipeline.py`) loads `ArticleDocument`, runs `ParallelDeepSearchClient.search`, picks citations via `_select_citations` (filters domains, sorts by date/score), and calls `EnhancementWriter.generate` with insights + existing sections/FAQ/citations.
- Application: `_apply_updates` appends new sections (must be non-empty), merges FAQ (deduplicates by question, trims to `ARTICLE_FAQ_MAX`), and chooses citation strategy (replace, merge single, or keep existing).
- Persistence and errors: `_persist` updates `Post` payload/body/citations/faq/lead/headline and commits; errors inside CLI loop are logged and trigger `db.rollback()` in `run_batch`; HTTP exposure for enhancer doesn’t exist yet.

## F) Data model touchpoints

- `posts` table (`app/models.py Post`): authoritative storage for slugs, SEO fields, body, taxonomy, `faq`, `citations`, `payload`, `created_at`, `updated_at` (DB defaults exist but new inserts set explicit timestamps).
- `gen_jobs` table (`app/models.py GenJob`): queue for transcript-based generation with status, errors, `article_id`, legacy URL fields, and audit timestamps; driven by admin queue + `GenRunner`.
- `ingest_log` table: lightweight log for ingest outcomes (currently unused by generation code).
- `rubrics` table: lookup for `rubric_code` → `name_pl` used during manual article generation.

## G) Refactor-ready seams (grounded in current code)

1) `create_article` in `app/main.py` mixes HTTP concerns with orchestration (transcript fetch, OpenAI calls, persistence); extracting a service-layer coordinator would make routing thinner without changing behavior.
2) The OpenAI assistant prompt assembly (`_compose_generation_brief` + `_build_system_instructions` in `app/services/__init__.py`) could be exposed as reusable helpers so both standard and transcript generators share a single builder.
3) `prepare_document_for_publication` currently takes a DB session only for slug uniqueness checks; decoupling slug/SEO normalization from DB writes would let CLI/admin flows reuse the logic before persistence.
4) `document_from_post` in `app/services/article_publication.py` re-normalizes missing fields (moved from `app/main.py`) to centralize the canonical post→document conversion for reuse by enhancers or exports.
5) `ArticleEnhancer.enhance_post` handles both research and writer orchestration; introducing a separable “research step” (already encapsulated by `ParallelDeepSearchClient.search`) would allow optional precomputation or caching without altering the writer contract.
6) Citation merging logic (`_merge_single_citation` vs replacement in `app/enhancer/pipeline.py`) is currently private; surfacing a pure helper would enable consistent handling in future routes or background tasks.
7) `EnhancementWriter._build_user_prompt` in `app/enhancer/writer.py` builds strings from dicts; extracting a structured prompt builder would make it easier to pass enriched research context while keeping the same OpenAI call.
8) `GenRunner` uses `get_transcript_generator` internally; accepting a generator interface via constructor (like `supadata_factory`) would make it reusable in tests or alternative pipelines without changing status handling.
9) `OpenAIClient.run_assistant` in `app/integrations/openai_client.py` polls until completion and then fetches recent messages; exposing the polling/reading steps would let generators swap in streaming or cached runs while preserving current error translation.
10) `ParallelDeepSearchClient` is instantiated ad hoc in the CLI; registering it as a dependency (similar to OpenAI generators) would allow future HTTP/worker reuse without changing the search call pattern.

## Step plan (next PRs)

1) "Route orchestration wrapper" — extract the `/artykuly` creation flow into a dedicated service while keeping handler signatures identical.
2) "Shared prompt builders" — centralize generation/enhancement prompt assembly utilities for both assistant generators and the enhancement writer.
3) "Publication helper module" — `document_from_post` now lives in the shared publication utility (`app/services/article_publication.py`) for reuse by enhancers/exporters.
4) "Enhancer seam cleanup" — factor citation handling and research invocation in `ArticleEnhancer` into pure helpers, readying for API exposure.
5) "Queue runner dependency injection" — allow `GenRunner` to accept generator instances for easier testing and reuse.
6) "Parallel client dependency provider" — add a configurable provider for `ParallelDeepSearchClient` to align with existing OpenAI/SupaData dependency patterns.

### Refactor updates

- Introduced `app/enhancer/helpers.py` to host reusable enhancer helpers.
- Research execution is centralized via `run_research_step`, making Parallel search callable outside `ArticleEnhancer`.
- Citation selection/merge rules now live in pure helpers for deterministic reuse.
- Enhancement application (sections/FAQ/citations) is handled by `apply_enhancement_updates` for consistent downstream use.
- GenRunner now accepts an injected article generator, keeping queue processing decoupled from transcript/publish internals.
- Admin queue wiring reuses `GeneratedArticleService` via an adapter so background jobs share the HTTP generation path.
- `ParallelDeepSearchClient` is obtained via `get_parallel_deep_search_client` (enhancer CLI uses the provider) for reuse across flows.

### Author-first adjustments

- Transcript/video generation now derives an `AuthorContext` (voice markers, tezy, cytaty) from the source transcript and passes it into prompt builders.
- Topic-mode briefs treat user guidance as the top style constraint while research remains wsparcie do faktów i cytowań.
- Transcript pipeline logs a warning when none of the extracted voice markers appear in the published text, keeping persistence unaffected.

### Output composition rules (PR C)

- Kontrakt kompozycji w `app/services/prompt_builders.py` (topic + transcript) utrzymuje narrację autora, używa researchu tylko do krótkich wstawek i cytowań, bez tonu akademickiego.
- Instrukcje generacji opisują opcjonalny blok „Kontekst i źródła (dla ciekawych)” (zwięzłe definicje + 3–8 źródeł) umieszczony pod koniec przed FAQ oraz FAQ jako odpowiedzi na brakujące pytania (może być puste, nie powtarza nagłówków).
- Cytowania mają wykorzystywać najlepiej dopasowane linki z research_sources zamiast przeładowania listy.
- Strażnik `_ensure_context_section_before_faq` w `app/services/article_publication.py` przenosi sekcję „Kontekst i źródła (dla ciekawych)” na koniec sekcji, jeśli FAQ istnieje.
- Enhancement writer (`app/enhancer/writer.py`) otrzymał tę samą wskazówkę: utrzymuj narrację autora, research dodawaj jako krótkie wstawki lub kompaktowy blok kontekstu.

## Stability hardening (minimal)

- FAQ sanitization in `app/services/article_publication.py` removes empty/duplicate entries (whitespace-trimmed, case-insensitive questions) before persistence and when returning posts.
- Video anti-duplicate logic in `app/services/generated_article_service.py` derives a `source_key` (e.g., `youtube:<id>`) stored under `payload.meta.source_key` and reuses the latest matching post instead of creating a new one.

## Observability

- Primary research and writer orchestration runs inside `GeneratedArticleService.generate_and_publish` (`app/services/generated_article_service.py`).
- When Parallel research fails or is unavailable, the service logs `error_stage="research"` and continues with writer-only generation (no HTTP 500).
- Look for structured events `article_generation_completed` / `article_generation_failed` and warnings `research_skipped_missing_config` to trace end-to-end behavior.
