# Skill: Local Deploy (Docker Compose)

## Purpose
Rebuild and restart only changed services on the local Docker Compose environment.

## Usage
Execute when the user says "로컬배포", "local deploy", or `/deploy-local`.

## Protocol Steps

1. **Detect Changed Services**
   - Run `git diff --name-only HEAD~1 HEAD` and `git status --short` to find changed files.
   - Map file paths to docker-compose service names:
     | Path prefix | Service name |
     |---|---|
     | `services/event-service/` | `event-service` |
     | `services/qa-service/` | `qa-service` |
     | `services/api-gateway/` | `api-gateway` |
     | `services/auth-service/` | `auth-service` |
     | `services/user-service/` | `user-service` |
     | `services/drama-service/` | `drama-service` |
     | `services/character-service/` | `character-service` |
     | `services/wiki-service/` | `wiki-service` |
     | `services/spoiler-policy-service/` | `spoiler-policy-service` |
     | `services/intelligence-service/` | `intelligence-service` |
     | `services/notification-service/` | `notification-service` |
     | `front/` | `frontend` |
   - If `infra/`, `build.gradle`, or `settings.gradle` changed → rebuild ALL services.
   - If user passes explicit service names, skip detection and use those.

2. **Confirm with User**
   - Show detected service list and ask for confirmation before rebuilding.

3. **Rebuild & Restart**
   ```bash
   docker compose -f infra/docker-compose.yml --env-file infra/.env up -d --build <service1> <service2> ...
   ```

4. **Verify**
   ```bash
   docker compose -f infra/docker-compose.yml --env-file infra/.env ps
   ```
   - Check that rebuilt services show "Up" status.
   - If a service shows errors, check logs with `docker logs <container>`.

## Notes
- Compose file location: `infra/docker-compose.yml`
- Frontend accessible at `http://localhost:3000/`
- API Gateway at `http://localhost:8080/`
- Spring Boot services take ~30-100s to start. Wait before verifying.
