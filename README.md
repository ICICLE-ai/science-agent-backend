# Science Agent Backend

Science Agent helps researchers carry out tasks using ICICLE services and resources through natural language. This backend connects the browser interface to the remote Science Agent, preserving user conversations and files and supplying the context needed for workflows such as ArrayMorph storage and Smart Labeler job submission.

**Tags:** Software, CI4AI

### License

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

This project continues the MIT license of the original
[ScienceAgentInterface](https://github.com/ICICLE-ai/ScienceAgentInterface), retaining its copyright notice.

## References

- [OpenAPI JSON](openapi.json)

- [Science Agent Frontend](https://github.com/ICICLE-ai/science-agent-frontend)
- [ICICLE](https://icicle.osu.edu/)
- [Smart Labeler](https://github.com/ICICLE-ai/smart_labeler)
- [ArrayMorph](https://github.com/ICICLE-ai/ArrayMorph)

## Acknowledgements

*National Science Foundation (NSF) funded AI institute for Intelligent Cyberinfrastructure with Computational Learning in the Environment (ICICLE) (OAC 2112606)*

---

# Tutorials

[Science Agent tutorials with screenshots](https://github.com/ICICLE-ai/science-agent-frontend#tutorials)

---

# How-To Guides

## Configure and start

Set the backend's private `.env`:

```env
DATABASE_URL=postgresql://USER:PASSWORD@DB_HOST:5432/DB_NAME
SCIENCE_AGENT_POD_URL=https://YOUR_AGENT_POD_HOST
TAPIS_BASE_URL=https://icicleai.tapis.io
TAPIS_ALLOWED_TENANTS=icicleai
SMART_LABELER_BASE_URL=https://smartlabelerbackend.pods.icicleai.tapis.io
FRONTEND_ORIGINS=https://scienceagent.pods.icicleai.tapis.io
```

Replace the database URL and service addresses with the provisioned deployment values. The DB must be reachable from the container, and its account needs table creation, alteration, and read/write permissions. For local development, set `FRONTEND_ORIGINS` to the actual local frontend origin.

`SCIENCE_AGENT_POD_TOKEN` is optional and is needed only if the agent pod gateway requires separate authentication. It does not replace the user's Tapis cookie token. S3 credentials are selected per user, not configured as global backend environment values.

Start using Docker Compose:

```sh
docker compose up -d
```

Compose downloads Python, installs the locked dependencies and source package, and starts the backend on port 8000. PostgreSQL and the agent pod are external services. Tables and migration history are initialized automatically at startup; no manual table setup is needed.

For local development instead:

```sh
uv sync
uv run uvicorn science_agent_backend.main:app --host 127.0.0.1 --port 8000
```

Use one worker in this version. API documentation is available at `/docs`; `/health` reports application availability, not remote service readiness.

---

# Explanation

The HTTP API specification is served at /openapi.json and saved in openapi.json
for release submission. Regenerate the file with
`uv run python -m science_agent_backend.openapi --output openapi.json` after API
changes. This exports documentation without connecting to PostgreSQL or the pod.
WebSocket behavior is documented separately in the x-websockets extension.

## User context, not a new agent per account

The backend verifies the `X-Tapis-Token` cookie and uses the validated identity to scope conversation, attachment, and S3 profile access. It sends the user's token in private request-specific context so the agent can call Smart Labeler and Tapis on that user's behalf.

The remote agent is shared. Each request receives its own files, recent conversation messages, selected S3 credentials, and workflow observations. This is application-level context separation, not a dedicated pod or an operating-system security boundary for every user.

## Responsibility boundaries

The frontend handles interaction, the backend handles authentication and persistence, and the agent pod performs service operations. PostgreSQL stores conversations, uploaded file bytes, S3 profiles, and recorded workflow observations. ArrayMorph and Smart Labeler work runs on the agent side rather than inside the backend container.

Migration history is maintained automatically by the backend. Uploaded files and credentials must be protected through restricted DB access, secure backups, and HTTPS. S3 secrets are currently stored without application-level encryption; they are not returned in public profile responses.

## Current scope

The integrated labeling flow accepts exactly one image. It reports observed submission and status information rather than treating submission as completed labeling.

The shared-agent guard currently serializes requests within one backend instance; multi-instance coordination is not implemented. The S3 browser API and original coding-agent execution commands have not been migrated. Hub cookie delivery, service permissions, and external job readiness remain deployment prerequisites.
