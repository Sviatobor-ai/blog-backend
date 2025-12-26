# Backend/Frontend maintenance fallback investigation

This note captures likely root causes and debugging steps for the homepage and article detail regressions that appeared after the first enhanced article was stored.

## Likely root causes (ranked)

1. **Invalid stored payload breaking `ArticleDocument` validation**
   * The detail endpoint returns `ArticleDocument.model_validate(post.payload)` when a stored payload exists; any new shape or too-short text from the enhancer will raise `ValidationError` unless caught.【F:app/main.py†L127-L169】【F:app/schemas/__init__.py†L14-L94】
   * Although `document_from_post` falls back to recomposed data, if the payload contains values that serialize but fail FastAPI’s response validation, the endpoint can still emit a 422/500 and the frontend may enter maintenance mode.
2. **List endpoint crashing due to strict response model**
   * `/artykuly` serializes each row into `ArticleSummary`; unexpected `None`/types from enhanced rows (e.g., tags array or timestamps) could trigger validation errors that propagate as 500s for the whole list response, leading the homepage to show the maintenance banner.【F:app/main.py†L206-L275】【F:app/schemas/__init__.py†L104-L134】
3. **Malformed MDX reconstructed from enhanced sections**
   * `compose_body_mdx` concatenates sections with `##`; if the enhancer injects headers containing `##` or empty titles/bodies, the stored `body_mdx` may not round-trip via `extract_sections_from_body`, leaving blank sections that the frontend fails to render or causing client-side MDX parse errors.【F:app/services/article_utils.py†L8-L35】
4. **FAQ length constraints exceeded**
   * The schema caps FAQ length at `ARTICLE_FAQ_MAX` (4). If the enhancer appends beyond this and truncation fails, response validation can throw, affecting both list (via `faq` serialization from payload) and detail endpoints.【F:app/article_schema.py†L7-L181】【F:app/enhancer/pipeline.py†L159-L167】
5. **Health endpoint/DB connectivity intermittently failing**
   * The frontend may treat `/health` or list failures as maintenance. Any transient DB error propagating through `health()` would set `db: "error"`, which could be interpreted as degraded state by the frontend.【F:app/main.py†L171-L198】

## Targeted debug steps

* **Log payload validation failures per slug**: Wrap `ArticleDocument.model_validate(post.payload)` with explicit logging of the slug and exception before falling back; capture the serialized payload snippet for the problematic article.
* **Isolate problematic rows in list queries**: Temporarily fetch posts individually within `/artykuly`, validating each `ArticleSummary` inside a try/except to log and skip the offending slug instead of failing the entire page.
* **Inspect MDX for the enhanced article**: Read `body_mdx` for the slug and run it through `extract_sections_from_body` to confirm section boundaries; verify the resulting array isn’t empty and matches `payload.article.sections` lengths.【F:app/services/article_utils.py†L21-L35】
* **Check FAQ count after enhancement**: Query `payload->'aeo'->'faq'` length for the slug to ensure it does not exceed 4; verify truncation in `app/enhancer/pipeline.py` is applied.
* **Frontend network inspection**: In DevTools, inspect the homepage list request; if status ≥500 or response schema differs from `{ meta, items }`, note the exact error and slug if present.

## Hardening ideas

* **Graceful degradation in list/detail**: Skip or sanitize individual posts whose payload or summary validation fails, logging the slug and reason, so a single bad row doesn’t take down the feed.【F:app/main.py†L127-L169】【F:app/main.py†L206-L275】
* **Stricter write-time validation**: Before saving enhanced content, revalidate with `ArticleDocument` and enforce `compose_body_mdx`/`extract_sections_from_body` symmetry to keep `payload` and `body_mdx` aligned.【F:app/services/article_publication.py†L31-L73】【F:app/services/article_utils.py†L8-L35】
* **MDX sanitization**: Normalize section titles/bodies to avoid nested `##` or empty strings prior to persistence; ensure `extract_sections_from_body` always yields at least one section and falls back gracefully.【F:app/services/article_utils.py†L8-L35】
* **FAQ guardrails**: Validate and trim FAQ arrays during enhancement and before response serialization so they respect `ARTICLE_FAQ_MAX`, avoiding runtime validation errors.【F:app/article_schema.py†L7-L181】【F:app/enhancer/pipeline.py†L159-L167】
* **Health signal isolation**: If the frontend interprets `/health` strictly, consider separating DB status from overall availability or caching the result to prevent transient DB blips from toggling maintenance mode.【F:app/main.py†L171-L198】
