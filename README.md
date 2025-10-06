# Blog Backend

Backend service for managing blog content and taxonomy.

## Environment

- `DATABASE_URL` — SQLAlchemy database URL (PostgreSQL in production).
- `APP_ENV` — set to `prod` in production to restrict CORS to trusted origins. Defaults to `dev`.

## Seeding

```sh
# python -m app.seeds.seed_rubrics
# python -m app.seeds.seed_rubrics --activate-all
# python -m app.seeds.seed_rubrics --deactivate-all
```

## API

- `GET /rubrics` — list rubrics (active by default, all with `?all=true`).
- `GET /posts` — paginated list of posts with optional search and section filter.
- `GET /posts/{slug}` — fetch a single post by slug.
- `GET /articles` — alias for `/posts`.
- `GET /articles/{slug}` — alias for `/posts/{slug}`.
