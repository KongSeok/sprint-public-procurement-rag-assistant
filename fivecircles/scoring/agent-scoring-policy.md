# Optional Agent Scoring Policy

Scoring is non-authoritative and runs only when the user or active workflow requests it.

Prefer evidence for:

- completed batch scope and acceptance criteria
- passing targeted and integration checks
- alignment with requirements and active specs
- secure handling of restricted corpus data
- low retry count without sacrificing correctness

Do not award points for API count, UI routes or database entities that do not belong to MidProjectRAG.
Scoring never changes product requirements or permits skipping validation.
