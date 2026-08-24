# Test Policy and Error Evolution

## Development Cycle Alignment

This policy belongs to the Test phase of the development cycle
(Requirements, Design, Implementation, Test, Maintenance).

## Mandatory Pre-Test Check

- Before any test execution, review this file to avoid repeating known failures.

## Test Error Logging

- During testing, summarize each error in a separate text file under `test/errorlogs/`.
- Navbar hover dropdown auto-open issue is logged and on hold; resume by reviewing the debug traces first.
- Each log entry must include the problem and the resolution approach.
- After resolving, record the prevention rule in this file.

## Error Handling Placement

- Operational and runtime error learnings are captured here.
- This file is non-authoritative for product behavior.
- It exists to prevent repeat mistakes during implementation.

## Economy: Design vs. Fixing After Errors

### Conclusion
Design-stage prevention is more economical for high-impact, repeatable errors.
Post-implementation fixes are only cheaper for low-impact or rare issues.

### When to Put Rules into Specs
Put rules into specs when:
- The error is likely to repeat across services.
- The fix requires multiple file edits (mapper + service + controller).
- The bug causes runtime failures or data corruption.
- The rule is structural (state transitions, mapping, auth, lifecycle).

Examples:
- State transition constraints (handover workflow)
- MyBatis record mapping (constructor resultMap only)
- Service readiness and dependency ordering

### When to Fix After Implementation
Fix after implementation when:
- It is an environment-specific issue.
- The fix does not change system-wide contracts.
- It is unlikely to reoccur across services.

Examples:
- Local Docker build timing
- Missing local binaries

---

## Recent Errors and Preventive Rules
