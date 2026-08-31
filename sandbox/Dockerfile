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

# The bind-mounted repo (host_repo_path -> /workspace) ends up owned by
# root inside the container regardless of chown above — a Windows/Docker
# Desktop bind-mount quirk. Modern git (2.35.2+, the CVE-2022-24765
# mitigation) refuses `git diff`/`git status`/etc. on a repo it doesn't own
# unless the directory is explicitly marked safe, and silently fails with
# "detected dubious ownership" / "not a git repository" — this was
# breaking every agent's ability to measure its own diff, discovered only
# after tracing a "0 files changed" false negative on a patch that had
# actually, verifiably been written correctly. `*` (not just /workspace)
# because the threat model this protects against — an attacker planting a
# malicious repo elsewhere on a shared host — doesn't apply inside an
# already-isolated, single-purpose container.
RUN git config --global --add safe.directory '*'

# Container is entered via `docker run ... sleep infinity` and driven with
# `docker exec` by sandbox/runner.py, so no ENTRYPOINT/CMD logic lives here.
CMD ["sleep", "infinity"]
