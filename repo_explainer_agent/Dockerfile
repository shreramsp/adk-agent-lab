# Recipe for the container image Cloud Run runs: Python + Node.js + Gemini CLI + git + the agent.
# Build context is this folder (repo_explainer_agent/), so it can be deployed on its own.

# start from a small official Python image (same 3.13 we use locally)
FROM python:3.13-slim

# Gemini CLI is a Node.js program; copy Node 24 out of the official Node image
# (Debian's own nodejs package is too old for Gemini CLI)
COPY --from=node:24-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:24-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

# git is needed to clone repos; --no-install-recommends keeps the image small
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# pin the exact Gemini CLI version we tested with
RUN npm install -g @google/gemini-cli@0.68.0 && npm cache clean --force

# install Python packages first (cached layer: only rebuilds when requirements change)
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# run as a normal user, not root: if anything ever went wrong, it can't touch the system
RUN useradd --create-home app
USER app
ENV HOME=/home/app

# adk looks for agent folders inside /app, so the code goes in /app/repo_explainer_agent
COPY --chown=app:app . /app/repo_explainer_agent

# Cloud Run tells the container which port to listen on via $PORT (8080 by default)
ENV PORT=8080
# browsers reach the private service through `gcloud run services proxy` on
# http://127.0.0.1:<port>. adk web rejects that as a foreign origin ("Forbidden: origin not
# allowed") unless we allow it. Safe: Cloud Run still requires your Google login for every request.
CMD ["sh", "-c", "adk web --host 0.0.0.0 --port ${PORT} --allow_origins 'regex:^http://(127\\.0\\.0\\.1|localhost):[0-9]+$' /app"]
