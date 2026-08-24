# Skill: Protocol for Server Deployment (SSH)

## Purpose
Standardize the backend/server deployment workflow using SSH to the test server.

## Usage
Execute this protocol when the user asks to "Server Deploy" (서버 배포해) or when backend changes need to be tested on the remote server.

## Protocol Steps

1.  **Preparation**
    - Ensure all local changes are committed.
    - Confirm the current branch is correct.
    - Resolve deployment inputs from project scripts, environment, or the user's instruction:
      - `CURRENT_BRANCH`: `git branch --show-current`
      - `REMOTE_ALIAS`: SSH host alias, for example a configured test server
      - `REMOTE_REPO_PATH`: repository path on the remote server
      - `COMPOSE_PATH`: compose directory or file, when Docker Compose is used

2.  **Execution (Automated)**
    - Prefer a project-provided deployment script under `fivecircles/test/`, `scripts/`, `ops/`, or `infra/`.
    - If multiple scripts exist, pick the one matching the user's requested environment and summarize the selected inputs before running it.

3.  **Manual Execution (Fallback)**
    - If the script fails, execute manually:
        ```bash
        # 1. Push
        CURRENT_BRANCH="$(git branch --show-current)"
        git push origin "$CURRENT_BRANCH"

        # 2. SSH & Deploy
        ssh "$REMOTE_ALIAS" "cd \"$REMOTE_REPO_PATH\" && git fetch && git checkout \"$CURRENT_BRANCH\" && git pull && docker compose up -d --build"
        ```

4.  **Log**
    - Record the deployment status in `update.md`.
