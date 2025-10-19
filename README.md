# Blog Backend

Backend service for managing blog content and taxonomy.

## Environment

- `DATABASE_URL` — SQLAlchemy database URL (PostgreSQL in production).
- `APP_ENV` — set to `prod` in production to restrict CORS to trusted origins. Defaults to `dev`.

## Migrations

Run the Alembic migrations after pulling new changes (including the `posts.payload`
column) to keep the database schema in sync:

```sh
alembic upgrade head
```

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
- `GET /articles` — paginated list of articles returning `{ meta, items }`.
- `GET /articles/{slug}` — fetch a single article document under the `post` key.

### Verifying article endpoints

Use the following commands against your deployment to ensure the `/articles` routes
are exposed and return the expected envelopes:

```sh
curl -s "https://<api-host>/openapi.json" | jq '.paths | keys | .[]' | grep '/articles'
curl -s "https://<api-host>/articles" | jq '{meta, items}'
curl -s "https://<api-host>/articles/<slug>" | jq '.post.slug'
```

The list endpoint must return the `{ meta, items }` envelope. The detail endpoint
wraps the document inside the `post` key.

## Changelog

- /articles now returns `{ meta, items }`.

AWS_REGION=eu-central-1
ACCOUNT_ID=685716749010
REPO=blog-backend
TAG=prod-3
IMAGE_URI=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO:$TAG

aws ecr get-login-password --region $AWS_REGION \
 | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

docker build -t $REPO:$TAG .
docker tag  $REPO:$TAG $IMAGE_URI
docker push $IMAGE_URI

SERVICE_ARN="arn:aws:apprunner:eu-central-1:685716749010:service/autoblogger-backend/08a8286c5d1c4b71b3c970b046d45cc2"
aws apprunner start-deployment --service-arn "$SERVICE_ARN"

uvicorn app.main:app --reload --port 8000
# Then open http://localhost:8000/health

# Отключить конвертацию путей MSYS (важно для /aws/...)
export MSYS2_ARG_CONV_EXCL="*"

http://localhost:3000/admin/app?t=9a8b7c6d-5e4f-3a2b-1c0d-efab12345678
