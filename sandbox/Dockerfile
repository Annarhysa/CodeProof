# Minimal, isolated execution image for running an evaluated repository's
# install/test/reproduction commands. No secrets, no host mounts beyond the
# repo working copy, restricted network by default at the docker-run layer.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates build-essential nodejs npm \
    && rm -rf /var/lib/apt/lists/*
# Debian's own nodejs/npm packages, not the nodesource setup script — that
# script was slow/unreliable to reach from this environment's network. The
# Debian-packaged Node version is older than upstream LTS but sufficient for
# `npm install` / `npm test` on typical repos; revisit if a benchmark case
# needs a newer Node feature.

RUN useradd -m -u 1000 sandbox
WORKDIR /workspace
RUN chown sandbox:sandbox /workspace
USER sandbox

# Container is entered via `docker run ... sleep infinity` and driven with
# `docker exec` by sandbox/runner.py, so no ENTRYPOINT/CMD logic lives here.
CMD ["sleep", "infinity"]
