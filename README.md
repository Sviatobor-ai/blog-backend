# Blog Backend

Backend service for managing blog content and taxonomy.

## Seeding

```sh
# python -m app.seeds.seed_rubrics
# python -m app.seeds.seed_rubrics --activate-all
# python -m app.seeds.seed_rubrics --deactivate-all
```

## API

- `GET /rubrics` — list rubrics (active by default, all with `?all=true`).
