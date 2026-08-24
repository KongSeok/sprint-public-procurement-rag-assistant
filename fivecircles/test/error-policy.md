# Error Policy

All APIs must use the same error format.

When runtime errors occur, review `fivecircles/architecture/specs/docker.md` and verify environment settings before debugging application logic.

Response:
{
  timestamp,
  path,
  code,
  message
}

Codes:
- FORBIDDEN (403)
- STATE_CONFLICT (409)
- VALIDATION_ERROR (400)
- NOT_FOUND (404)
