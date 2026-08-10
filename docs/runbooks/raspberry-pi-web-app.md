# Runbook: deploying the web app to the Raspberry Pi

The web app (`app/polar_web_app/`) doesn't run in AWS at all — it's built as a
Docker image by `.github/workflows/deploy-web-app.yml` (manual
`workflow_dispatch` only, same no-auto-deploy convention as
`deploy-service.yml`), pushed to a **private** GitHub Container Registry
image, and pulled/run on a Raspberry Pi at home. This is a third runtime
pattern alongside this repo's AWS Lambda services and local dev — nothing
here touches the AWS account's Lambda/API Gateway/SQS pipeline.

## Prerequisites (one-time)

Not all of these run on the Pi itself — steps 4's AWS/Terraform commands need
the `polar-app-prod` CLI profile and a Terraform working directory with
access to the real state, neither of which belong on the Pi (it's
deliberately only ever given the narrow `rpi-web-app` credential, never
`polar-app-prod`). Each step below says which machine it runs on.

1. **(On the Pi)** **Confirm architecture** — the published image is multi-platform
   (`linux/amd64` + `linux/arm64`); confirm the Pi is actually one of those
   before relying on it:

   ```sh
   uname -m
   ```

   `aarch64` → `linux/arm64` (current Pi 4/5 on a 64-bit OS). Anything else,
   stop and re-check the build platforms in `deploy-web-app.yml`.

2. **(On the Pi)** **Install Docker** (with the Compose plugin) if not already present —
   follow Docker's own Raspberry Pi OS / Debian install instructions; not
   repeated here since it's generic, not specific to this app.

3. **(On the Pi)** **Authenticate to GHCR.** The image is private (deliberate — see
   `CLAUDE.md`'s git-workflow section on this repo staying private), so the
   Pi needs a GitHub token with `read:packages` scope. Create one at
   github.com → Settings → Developer settings → Personal access tokens
   (fine-grained, scoped to this repo, `read:packages` only), then on the Pi:

   ```sh
   read -r -s GHCR_TOKEN   # paste the token, then press enter
   echo "$GHCR_TOKEN" | docker login ghcr.io -u <your-github-username> --password-stdin
   unset GHCR_TOKEN
   ```

   This is a one-time step — Docker caches the credential in
   `~/.docker/config.json` on the Pi.

4. **(On your own machine, not the Pi)** **Get a least-privilege AWS
   credential for the Pi — do not reuse the `polar-app-prod` CLI profile on
   the Pi itself.** `terraform/environments/prod/web_app.tf` already creates
   the IAM identity and its policy — scoped to exactly `dynamodb:Query`/
   `GetItem` on the `exercise_data` table (via
   `exercise_insights.core.get_exercise_metrics`) and `s3:GetObject`/
   `PutObject` on the `web_app_context` bucket (`src/context_store.py`),
   nothing broader. It deliberately stops short of creating the access key
   itself (same "Terraform creates the container, the credential is
   generated out-of-band" pattern as the app secret in `secrets.tf` — an
   `aws_iam_access_key` resource would put the secret key in Terraform state
   in plaintext). Both commands below need the `polar-app-prod` CLI profile
   and this repo's Terraform state, so they only ever make sense on the
   machine you already ran `terraform apply` from — not the Pi, which never
   gets that profile. After `terraform apply` has run at least once:

   ```sh
   aws iam create-access-key --user-name rpi-web-app --profile polar-app-prod
   ```

   Also grab the bucket name for `CONTEXT_BUCKET`:

   ```sh
   terraform -chdir=terraform/environments/prod output -json s3_bucket_names | jq -r .web_app_context
   ```

   Carry the `AccessKeyId`/`SecretAccessKey`/bucket name over to the Pi
   yourself (e.g. typed in over SSH, or copy-pasted into the editor in the
   next step) — this is the only place they get written down.

5. **(On the Pi)** **Create the `.env` file** next to `docker-compose.yml`
   (this file is gitignored — create it directly on the Pi, never commit
   it). Touch an empty file, lock down its permissions, then fill in each
   value with a text editor rather than a one-line command, so nothing
   sensitive ends up in shell history:

   ```sh
   touch .env
   chmod 600 .env
   nano .env
   ```

   Add these keys (values on the right of `=`, one per line):

   ```
   ANTHROPIC_API_KEY=
   SUPABASE_URL=
   SUPABASE_KEY=
   POLAR_USER_ID=
   CONTEXT_BUCKET=
   AWS_ACCESS_KEY_ID=
   AWS_SECRET_ACCESS_KEY=
   AWS_DEFAULT_REGION=us-east-1
   ```

## Deploying / updating

```sh
docker compose pull
docker compose up -d
docker compose logs  # Ctrl-C to stop following, container keeps running
```

`docker compose pull` always pulls whatever `deploy-web-app.yml` most
recently pushed to the `latest` tag — this is a deliberate manual step, not
an auto-update; run it only when you actually want to move to a new build.

## Rolling back

If a new image misbehaves, pin to a specific prior build by git SHA instead
of `latest`:

```sh
IMAGE_TAG=<git-sha-of-the-known-good-build> docker compose up -d
```

(Find candidate SHAs from the repo's commit history or the
`deploy-web-app.yml` run history in GitHub Actions.)

## Verifying it's actually working

```sh
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/login
```

`200` means the app is up. A real end-to-end check (login, ask a question,
confirm onboarding/profile/data-fetch behavior) still needs a browser — see
`app/polar_web_app/README.md`.
