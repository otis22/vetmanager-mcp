# Stage 493 rollback manifest

- Previous accepted release SHA: `a85cb35db38f0d0239836c7ce546c9e26990daf9` (main after 492).
- Previous production image ID supplied by the curator: `sha256:b26a2b7864102281a5fe2714d9bfc306b45cb808467150e6ec592d218149497d`. This is the **production 492 release**, distinct from the locally retained 492 candidate image used to generate the synthetic Fernet test token. The executor has not accessed production; the curator must cross-check this ID against the stored release artifact and running workers before deploy.
- Previous Python base digest: `ghcr.io/otis22/python:3.12-slim@sha256:139b146ecf6cadf1960a88887c83846bd030bf1bc0a478fae48215c49917c075`.
- Candidate base digest: `ghcr.io/otis22/python:3.12-slim@sha256:d632bda0952ef8a17cd233c1f50b987c6ea31423e9b797aad792fd8f8762e336`.
- Baseline Alembic versions tree: `480bc02b296596b4c67ee21252d94b00b65aea2d`; stage 493 introduces no migration. Thus the old image remains compatible with the unchanged schema after application deploy, provided no independent migration occurs between release and rollback. The curator must verify the deployed Alembic revision and backup before release and before any rollback.
- Fernet compatibility was checked in both directions with synthetic credentials: a token emitted by the accepted 492 candidate decrypted in the new 493 production candidate, and a token emitted by the new 493 production candidate decrypted in the 492 production candidate. The actual prior production image ID above is curator-supplied and was not executed by this agent.

Rollback is a **manual curator decision** under the application runbook. Preserve the prior image and release SHA before deploying. Restore the prior application image only after checking schema revision, data backup and worker health. Never automate database or host rollback. This manifest is preparation, not evidence that production was rolled back or changed.
