# Implementation Rules (Preventive)

These rules are promoted from test/learn-from-log.md and are mandatory.

## Mapping and Persistence

- When using Java records with MyBatis, always use constructor-based resultMap.
- Do not use useGeneratedKeys with record DTOs; insert then query by key.

## Registration Constraints

- Pre-check unique keys (e.g., username) before insert.
- Return 409 CONFLICT for duplicate keys.

## Service Readiness

- Use healthcheck + readiness-based startup ordering for dependent services.
- Configure gateway retries for upstream connection failures.

## JWT Propagation

- Gateway validates JWT and passes user context via headers.
- Services trust headers and avoid re-parsing JWT for each request.

## Runtime Stack Policy

- Backend services use Spring MVC (Servlet) with blocking JDBC/MyBatis.
- api-gateway uses WebFlux; do not introduce WebFlux in services unless moving data access to non-blocking drivers (e.g., R2DBC).

## Work Folder Alignment

- The `work/` folder (plans, todo) must follow these implementation rules.
- Planning tasks should be tracked in `architecture/todolist.md` and related plan files; specs remain the source of truth for behavior.
