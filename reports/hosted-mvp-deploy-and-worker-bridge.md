# Hosted MVP Deployment and Worker Bridge

## Result

`DEPLOYMENT_CREDENTIAL_REQUIRED`

The Agent Hub source is deployment-ready and `langgraph validate --config
langgraph.json` reports seven valid graphs.  A real LangSmith Deployment was
not created because no `LANGSMITH_API_KEY`, `LANGGRAPH_HOST_API_KEY`, or
`LANGCHAIN_API_KEY` is configured.  `langgraph deploy --help` confirms one of
these keys is required.

## Worker contract

The Mac-side worker exposes `POST /execute`. It accepts only a frozen
`flutter_study` task with a matching base revision, non-empty repository
relative allowed paths, and validation identifiers (`flutter_analyze` or
`flutter_test:<path>`). It rejects external repositories, path escapes, and
arbitrary shell commands.

The worker creates an isolated worktree, reconstructs external local path
dependencies through worker-local configuration, runs `flutter pub get` before
Codex, guards tracked and untracked changes, formats only changed Dart files,
runs the task's targeted tests, compares `flutter analyze` against a baseline,
and returns a complete diff including untracked new files. It never commits or
pushes.

## Graph integration

`development` now has an `execute_code` node. It sends only the frozen task to
`AGENT_HUB_CODE_WORKER_ENDPOINT`; no local business path is embedded in graph
source or request state. Worker blocked/failure statuses are returned unchanged.

## Verification

- Bridge request validation and untracked diff collection: PASS.
- Graph-to-worker result propagation: PASS.
- Existing bootstrap/runtime regressions: PASS.
- `langgraph validate --config langgraph.json`: PASS (7 graphs).
- Hosted deployment: blocked only by absent LangSmith/LangGraph API credential.

## Exact next input

Configure a LangSmith deployment API key and deployment name, expose the local
worker endpoint to that deployment, and configure the worker's local
`AGENT_HUB_PRIMARY_REPOSITORY_PATH` plus any external sibling path provider
mapping. Then submit one frozen task using the `POST /execute` schema.
