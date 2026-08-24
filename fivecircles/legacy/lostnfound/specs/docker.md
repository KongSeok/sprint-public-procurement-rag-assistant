# Docker Specification

This document defines how services are built and executed using Docker.
It does NOT define application logic.

Authority:
- Application behavior is defined in workflow.md
- This document defines runtime wiring only

---

## Containerization Policy

- Each backend service runs in its own container
- One database container (MySQL)
- No distributed transaction handling
- Services communicate via HTTP (REST)

---

## Services
