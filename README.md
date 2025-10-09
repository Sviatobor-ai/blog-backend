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

AWS_REGION=eu-central-1
ACCOUNT_ID=685716749010
REPO=blog-backend
TAG=prod-2
IMAGE_URI=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO:$TAG

aws ecr get-login-password --region $AWS_REGION \
 | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

docker build -t $REPO:$TAG .
docker tag  $REPO:$TAG $IMAGE_URI
docker push $IMAGE_URI
