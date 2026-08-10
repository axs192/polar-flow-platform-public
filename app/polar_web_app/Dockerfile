# Build from the REPO ROOT, not this directory: this project depends on
# services/exercise-insights as a local editable package, so both directories
# must be in the build context, at the same relative nesting as the real repo
# (so `[tool.uv.sources]`'s `../../services/exercise-insights` path resolves).
#
#   docker buildx build -f app/polar_web_app/Dockerfile --platform linux/amd64,linux/arm64 .
#
# (from the repo root -- see the repo-root .dockerignore, which scopes the
# context down to just these two directories).

FROM python:3.13-slim-bookworm AS builder

WORKDIR /repo

# Install curl and certificates needed by the uv installer
RUN apt-get update \
	&& apt-get install -y --no-install-recommends curl ca-certificates \
	&& rm -rf /var/lib/apt/lists/*

# Install uv straight to /usr/local/bin, not the installer's default
# $HOME/.local/bin -- that would land under /root, whose 700 permissions
# the runtime stage's non-root user couldn't traverse into.
ENV UV_INSTALL_DIR=/usr/local/bin
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh

# Both directories are needed for the editable exercise-insights dependency to
# resolve; copied in full together since uv needs its real source to build it,
# not just its pyproject.toml, so there is no cache-friendly manifest-only step.
COPY services/exercise-insights/ services/exercise-insights/
COPY app/polar_web_app/ app/polar_web_app/

WORKDIR /repo/app/polar_web_app
RUN uv sync --frozen


FROM python:3.13-slim-bookworm AS runtime

# Runs as a dedicated non-root user, not the image default (root) -- standard
# container hardening, cheap to do, no reason not to.
RUN useradd --create-home --shell /usr/sbin/nologin appuser

WORKDIR /repo/app/polar_web_app

COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv
COPY --from=builder /usr/local/bin/uvx /usr/local/bin/uvx
# Carries the .venv uv created during sync, plus both projects' source.
COPY --from=builder --chown=appuser:appuser /repo /repo

ENV PYTHONUNBUFFERED=1

USER appuser

CMD ["uv", "run", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
