---
name: Duplicate workflow port collision
description: Two workflows both try to bind port 5000; only the artifact-managed one should run.
---

## Rule
The standalone "Linux Operations Portal" workflow and the artifact-managed "artifacts/api-server: LOP" workflow both run `python run.py` on port 5000. Only **artifacts/api-server: LOP** should be running. If the standalone one starts, kill port 5000 with `fuser -k 5000/tcp` and restart the artifact workflow.

**Why:** The artifact workflow is the canonical one managed by artifact.toml. The standalone workflow is a legacy entry that was not removed.

**How to apply:** Always restart "artifacts/api-server: LOP", never "Linux Operations Portal". If the LOP workflow fails with "address already in use", kill 5000/tcp first.
