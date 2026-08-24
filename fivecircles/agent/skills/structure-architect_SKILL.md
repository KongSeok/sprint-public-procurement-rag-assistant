---
name: structure-architect
description: Use this skill when designing, reviewing, or refactoring a codebase structure for maximum maintainability and extensibility. Trigger it before large implementation work, new feature modules, architectural refactors, folder/file tree decisions, module boundary design, dependency rule definition, MSA readiness assessment, or service extraction planning.
---

# Structure Architect Skill

You design codebase structure as a binding architecture contract, not as a decorative folder tree.

Your mission is to maximize:
1. maintainability
2. extensibility
3. clear module ownership
4. low coupling
5. high cohesion
6. testability
7. future service extraction readiness
8. minimal accidental complexity

Use this skill before implementation when structure, module boundaries, architecture style, or long-term maintainability are relevant.

---

## Core Method: Structure Contract Design

Follow **Structure Contract Design**, abbreviated as **SCD**.

SCD means:

1. Understand the product and feature landscape.
2. Select the architecture style that fits the current and future scale.
3. Define module boundaries before writing or moving code.
4. Write the folder/file tree as a contract.
5. Define dependency direction and forbidden imports.
6. Define file placement rules.
7. Define module public APIs.
8. Define data ownership and integration contracts.
9. Define MSA readiness and service extraction criteria.
10. Add review gates and scoring hooks.

Do not treat the folder tree as a suggestion. Treat it as a project-level agreement that Codex and humans must follow.

---

## Default Architecture Philosophy

Prefer:

```txt
Feature-based Modular Monolith
+ Clean/Hexagonal internal module structure
+ MSA-ready boundaries
```

This means:

- Start with one deployable application unless there is a clear reason to split services.
- Divide the codebase into business capability modules.
- Keep each module internally clean, testable, and replaceable.
- Design modules so they can later be extracted into services if needed.
- Avoid premature microservices.

Use the principle:

```txt
split-ready, not split-now
```

A module should be ready to become a service later, but it should not become a service before operational, scaling, team, or deployment needs justify it.

---

## Complexity Calibration

Before proposing a structure, classify the project scale.

### Tiny / MVP

Use a simple structure when:
- the app has only a few features
- one developer or a very small team owns it
- business rules are simple
- service extraction is unlikely soon

Acceptable simplified pattern:

```txt
src/
  app/
  modules/
    <feature>/
      domain/
      application/
      infrastructure/
      interface/
      index.ts
  shared/
  tests/
architecture/
  design.md
  structure-contract.md
```

### Growing Product

Use the default MSA-ready modular monolith when:
- features are increasing
- business logic matters
- external systems may change
- future service extraction is possible
- multiple developers may work on separate areas

Preferred pattern:

```txt
src/
  app/
    bootstrap/
    config/
    composition/
    routes/

  modules/
    <module-name>/
      domain/
        entities/
        value-objects/
        policies/
        events/
      application/
        commands/
        queries/
        use-cases/
        ports/
      infrastructure/
        persistence/
        external/
        messaging/
      interface/
        http/
        cli/
        event-handlers/
      contracts/
        public-api.ts
        events.ts
        schemas.ts
      index.ts
      module-contract.md
      tests/

  shared/
    kernel/
    primitives/
    errors/
    result/
    clock/
    logger/

  tests/
    integration/
    e2e/

architecture/
  design.md
  structure-contract.md
  module-boundaries.md
  service-extraction-plan.md
```

### MSA / Service Architecture

Only recommend MSA when there are strong reasons, such as:
- independent deployment is required
- teams own different business capabilities
- one module has very different scaling needs
- failure isolation is required
- service-level ownership is clear
- data ownership is stable
- observability, CI/CD, and deployment maturity are sufficient

MSA-ready monorepo pattern:

```txt
apps/
  api-gateway/
  admin-web/
  user-web/

services/
  <service-name>/
    src/
      domain/
      application/
      infrastructure/
      interface/
    tests/
    service-contract.md

packages/
  contracts/
    <service-name>/
      commands.ts
      events.ts
      schemas.ts
  shared-kernel/
  config/
  test-utils/

infra/
  docker/
  kubernetes/
  terraform/

architecture/
  system-design.md
  service-boundaries.md
  integration-contracts.md
  service-extraction-plan.md
```

If MSA is not clearly justified, recommend Modular Monolith first and document service extraction candidates.

---

## Step 1: Understand the Feature Landscape

Before designing structure, identify:

- primary user-facing features
- business capabilities
- likely modules or bounded contexts
- data ownership candidates
- external systems and APIs
- integrations that may fail or change
- expected future features
- likely high-change areas
- team size and ownership model
- deployment and scaling needs
- testing expectations
- compliance, security, or audit constraints

Ask clarifying questions only when essential. If the user expects forward progress, make explicit assumptions and continue.

Do not design the folder tree before identifying boundaries.

---

## Step 2: Select the Architecture Style

Choose one primary architecture style:

- Layered Architecture
- Feature-based Modular Architecture
- Modular Monolith
- Clean Architecture
- Hexagonal Architecture / Ports and Adapters
- DDD-inspired Bounded Contexts
- Microservices / Service Architecture

Default choice:

```txt
Feature-based Modular Monolith
with Clean/Hexagonal boundaries inside each module
```

When selecting architecture, always explain:

1. selected architecture
2. why it fits
3. rejected alternatives
4. tradeoffs
5. expected evolution path
6. MSA readiness impact

Example decision:

```txt
Selected:
Feature-based Modular Monolith with Clean/Hexagonal module internals.

Why:
The project needs clear feature boundaries and maintainable business logic, but there is not yet enough operational justification for microservices.

Rejected:
Flat MVC, because feature ownership will blur as the app grows.
Premature MSA, because it adds deployment, observability, data consistency, and network complexity before the boundaries are proven.

Evolution:
Each module will expose a public API and own its data, so selected modules can later be extracted into services.
```

---

## Step 3: Define Module Boundaries

A module should represent a business capability, feature area, or bounded context.

Good module examples:

```txt
auth
billing
orders
catalog
notifications
reporting
identity
payments
```

Avoid module names based only on technical layers:

```txt
controllers
services
repositories
models
helpers
utils
```

For each module, define:

- responsibility
- owned data
- public API
- forbidden responsibilities
- allowed dependencies
- incoming events
- outgoing events
- external dependencies
- expected tests
- extraction readiness criteria

Use this table format:

```md
| Module | Responsibility | Owns Data | Public API | Incoming | Outgoing | Must Not Own |
|---|---|---|---|---|---|---|
| billing | invoices, payments, subscriptions | invoices, payments | modules/billing/index.ts | OrderCreated | InvoiceCreated, PaymentSucceeded | user passwords, product catalog |
```

Boundary rule:

```txt
Things that change for the same reason belong together.
Things that change for different reasons should be separated.
```

---

## Step 4: Define Data Ownership

Every important data concept must have one logical owner.

For each module, define:

```txt
owns:
  - tables / collections
  - aggregates
  - domain events
  - write permissions

may read:
  - read models
  - public API responses
  - integration events

must not write:
  - other modules' owned data
```

Rules:

- A module may directly write only its owned data.
- A module must not mutate another module's data directly.
- Cross-module changes must go through public APIs, commands, events, or application services.
- Shared database is allowed early, but logical ownership must still be documented.
- If a data object has two owners, the boundary is not clear enough.

---

## Step 5: Create the Folder/File Tree Contract

Produce a tree that acts as a binding contract.

For every top-level and module-level folder, define:

- purpose
- what belongs there
- what must not belong there
- naming convention
- allowed import direction
- examples of valid files

Every proposed folder must have a responsibility. Avoid decorative folders.

Default production tree:

```txt
src/
  app/
    bootstrap/
    config/
    composition/
    routes/

  modules/
    <module-name>/
      domain/
        entities/
        value-objects/
        policies/
        events/
      application/
        commands/
        queries/
        use-cases/
        ports/
      infrastructure/
        persistence/
        external/
        messaging/
      interface/
        http/
        cli/
        event-handlers/
      contracts/
        public-api.ts
        events.ts
        schemas.ts
      index.ts
      module-contract.md
      tests/

  shared/
    kernel/
    primitives/
    errors/
    result/
    clock/
    logger/

  tests/
    integration/
    e2e/
```

Folder meanings:

```txt
app/
  Application bootstrap, dependency composition, global config, route registration.
  Must not contain business rules.

modules/<module>/domain/
  Pure domain entities, value objects, policies, domain events, business invariants.
  Must not import framework, database, HTTP, UI, queue, or external API code.

modules/<module>/application/
  Use cases, commands, queries, application services, ports.
  Orchestrates domain logic.
  May depend on domain.
  Must not depend on concrete infrastructure.

modules/<module>/infrastructure/
  Database adapters, external API clients, queue implementations, persistence mapping.
  Implements ports defined by application or domain.

modules/<module>/interface/
  HTTP handlers, controllers, CLI handlers, event handlers, presentation adapters.
  Calls application use cases.
  Must not contain core business rules.

modules/<module>/contracts/
  Public schemas, events, commands, and integration contracts.
  Used to prepare for service extraction.

modules/<module>/index.ts
  Public module API.
  Other modules must import only from here or from documented contracts.

shared/
  Truly shared primitives and cross-cutting tools.
  Must not contain feature-specific business logic.
```

---

## Step 6: Define Dependency Rules

Default allowed dependency direction:

```txt
interface → application
application → domain
infrastructure → application/domain
app/composition → modules and infrastructure
tests → target under test
```

Default forbidden dependencies:

```txt
domain → infrastructure
domain → interface
domain → app
domain → database clients
domain → HTTP frameworks
domain → external APIs
application → concrete infrastructure
shared → modules/*
module A → module B internal files
module A domain → module B domain directly
```

Public API rule:

Allowed:

```ts
import { createInvoice } from "@/modules/billing";
```

Forbidden:

```ts
import { BillingRepository } from "@/modules/billing/infrastructure/persistence/billing-repository";
import { InvoiceEntity } from "@/modules/billing/domain/entities/invoice";
```

Cross-module rule:

```txt
Other modules may use only:
- modules/<module>/index.ts
- modules/<module>/contracts/*
- explicitly documented public APIs
```

If direct internal imports seem necessary, stop and propose a contract update.

---

## Step 7: Define File Placement Rules

Use these defaults:

```txt
New business entity:
  modules/<feature>/domain/entities/

New value object:
  modules/<feature>/domain/value-objects/

New domain policy:
  modules/<feature>/domain/policies/

New domain event:
  modules/<feature>/domain/events/

New use case:
  modules/<feature>/application/use-cases/

New command:
  modules/<feature>/application/commands/

New query:
  modules/<feature>/application/queries/

New port/interface for infrastructure:
  modules/<feature>/application/ports/

New database adapter:
  modules/<feature>/infrastructure/persistence/

New external API client:
  modules/<feature>/infrastructure/external/

New queue or messaging adapter:
  modules/<feature>/infrastructure/messaging/

New HTTP route/controller:
  modules/<feature>/interface/http/

New CLI command:
  modules/<feature>/interface/cli/

New event handler:
  modules/<feature>/interface/event-handlers/

New public contract:
  modules/<feature>/contracts/

New shared primitive:
  shared/primitives/

New cross-cutting utility:
  shared/<specific-purpose>/
```

Shared rule:

```txt
Put code in shared only if:
1. it is used by at least two modules, or
2. it is a stable cross-cutting primitive, or
3. it is intentionally part of the shared kernel.

Do not move feature logic into shared just to avoid duplication.
Prefer small duplication over wrong ownership.
```

---

## Step 8: Define Module Contract

Every major module should have a `module-contract.md`.

Template:

```md
# <Module Name> Module Contract

## Responsibility

Describe what this module owns.

## Owned Data

- tables / collections
- aggregates
- write permissions

## Public API

Other modules may use only:

- `modules/<module>/index.ts`
- `modules/<module>/contracts/public-api.ts`
- `modules/<module>/contracts/events.ts`
- `modules/<module>/contracts/schemas.ts`

## Forbidden Access

Other modules must not import:

- `modules/<module>/domain/*`
- `modules/<module>/application/*`
- `modules/<module>/infrastructure/*`
- `modules/<module>/interface/*`

## Incoming Events

- EventName

## Outgoing Events

- EventName

## External Dependencies

- dependency name
- failure mode
- retry or fallback policy

## Tests

- domain tests
- use case tests
- integration tests
- contract tests

## Extraction Readiness

This module can become a service if:

- no other module imports its internals
- all external calls go through contracts or ports
- owned data is not directly mutated by other modules
- tests can run independently
- public API is explicit
- integration events or commands are documented
```

---

## Step 9: Define MSA Readiness

Do not recommend microservices prematurely.

A module is MSA-ready only if:

```txt
- it has clear business ownership
- it owns its data
- it exposes a documented public API
- it has no unapproved internal imports from other modules
- other modules do not write its data directly
- integration contracts are documented
- it can be tested independently
- it does not depend on global application state
- failure modes are known
- observability requirements are known
```

MSA extraction candidates should be scored:

```md
| Candidate | Reason | Data Ownership Clear? | Independent Scaling? | Independent Deployment? | Contract Ready? | Extraction Risk |
|---|---|---:|---:|---:|---:|---|
| billing | payment failures need isolation | yes | medium | high | medium | medium |
```

Recommend extraction only when the benefit exceeds the operational cost.

Common extraction triggers:

```txt
- module needs independent deployment
- module has unique scaling requirements
- module has distinct team ownership
- module causes risky whole-app deployments
- module has failure/retry behavior that should be isolated
- module's data ownership is stable
- integration contracts are mature
```

Common reasons to avoid MSA for now:

```txt
- team is small
- boundaries are still changing
- CI/CD is immature
- observability is weak
- data ownership is unclear
- no clear independent deployment need
- service contracts would change constantly
```

---

## Step 10: Define Service Extraction Protocol

When extracting a module to a service, preserve the internal architecture.

From:

```txt
src/modules/billing/
  domain/
  application/
  infrastructure/
  interface/
  contracts/
```

To:

```txt
services/billing-service/
  src/
    domain/
    application/
    infrastructure/
    interface/
  service-contract.md
```

Extraction protocol:

1. Verify no other module imports internal files.
2. Move public contracts to `packages/contracts/<service>/` if needed.
3. Replace in-process calls with a client, command, query, or event.
4. Preserve domain and application code as much as possible.
5. Replace local infrastructure with service-specific infrastructure.
6. Add contract tests.
7. Add integration tests for cross-service communication.
8. Update `architecture/service-boundaries.md`.
9. Update deployment and observability docs.
10. Update `AGENTS.md` rules if needed.

---

## Step 11: Define Testing and Boundary Gates

Every structure proposal must include testing hooks.

Suggested tests:

```txt
domain tests:
  validate pure business rules without infrastructure

use case tests:
  validate application behavior with fake ports

integration tests:
  validate adapters, persistence, external APIs

contract tests:
  validate public API, event schemas, command/query contracts

boundary tests:
  validate forbidden imports and module visibility rules
```

Suggested structure gate:

```txt
Integrate is allowed only if:
- no forbidden dependency direction exists
- no module imports another module's internals
- no new top-level folder exists without contract update
- no domain code imports infrastructure or framework code
- no feature-specific business logic was moved into shared
- structure score is 80 or higher
```

---

## Step 12: Score the Structure

Use this scoring rubric.

```md
# Structure Score

Total: 100

## Cohesion, 20
- Files that change together are grouped together.
- Each module has one clear reason to change.
- Module responsibilities are not vague.

## Coupling, 20
- Dependencies flow in the allowed direction.
- Modules do not import each other's internals.
- Public APIs are explicit.

## Extensibility, 20
- New features have an obvious destination.
- External systems can be replaced without touching domain logic.
- Future service extraction remains possible.

## Testability, 15
- Domain logic can be tested without infrastructure.
- Use cases can be tested without booting the whole app.
- Contract and integration tests are identifiable.

## Clarity, 15
- Folder names express responsibility.
- File placement rules are unambiguous.
- Module contracts are readable.

## Simplicity, 10
- No premature abstractions.
- No decorative folders.
- No premature microservices.
```

Critical violations:

```txt
- domain imports infrastructure
- module imports another module's internal files
- shared contains feature-specific business logic
- two modules own the same data
- new top-level folder added without contract update
```

If a critical violation exists, structure approval fails regardless of score.

---

## Required Output Format

When asked to design or revise structure, respond with:

```md
# Architecture / Structure Proposal

## 1. Assumptions

## 2. Architecture Decision

## 3. Why This Architecture Fits

## 4. Rejected Alternatives

## 5. Module Boundary Map

## 6. Data Ownership Map

## 7. Folder/File Tree Contract

## 8. Folder Responsibility Rules

## 9. Dependency Rules

## 10. File Placement Rules

## 11. Public API and Contract Rules

## 12. MSA Readiness Assessment

## 13. Service Extraction Candidates

## 14. Testing and Boundary Gates

## 15. Structure Score

## 16. Risks and Tradeoffs

## 17. Required Documentation Updates

## 18. Suggested AGENTS.md Updates

## 19. Next Implementation Steps
```

Keep the proposal concrete. Include actual folder names and example imports where useful.

---

## Existing Repository Behavior

If the repository already exists:

1. Inspect the current tree before proposing changes.
2. Infer the current architecture.
3. Identify boundary violations.
4. Identify coupling hotspots.
5. Identify vague shared or utils folders.
6. Identify domain code that imports infrastructure.
7. Identify modules that could become service candidates.
8. Propose the smallest structure improvement that increases maintainability.
9. Avoid unnecessary rewrites.
10. Preserve working code unless the structure contract requires change.

When refactoring, prefer staged migration:

```txt
1. document current structure
2. define target structure
3. add public APIs
4. move files module by module
5. replace forbidden imports
6. add boundary tests
7. update AGENTS.md and architecture docs
```

---

## New Project Behavior

If starting a new project:

1. Define architecture decision first.
2. Define module candidates.
3. Define data ownership.
4. Write folder/file tree contract.
5. Write module contract template.
6. Write dependency rules.
7. Write extension protocol.
8. Write structure score gate.
9. Then implement scaffolding.

Do not implement business features before the structure contract exists unless the user explicitly asks for a spike or prototype.

---

## Extension Protocol

Before adding a new feature, answer:

```txt
1. Is this a new module or part of an existing module?
2. Which module owns the data?
3. Which public API or contract is needed?
4. Which files will be added?
5. Which imports are allowed?
6. Which tests prove the boundary remains valid?
7. Does the structure contract need updating?
8. Does any module contract need updating?
9. Does this affect MSA readiness?
```

Before adding a new folder, answer:

```txt
1. Why are existing folders insufficient?
2. What exact responsibility does the new folder own?
3. What must not be placed there?
4. Which dependency rules apply?
5. Which contract document must be updated?
```

---

## Documentation Updates

When structure decisions are made, update or propose updates to:

```txt
architecture/design.md
architecture/structure-contract.md
architecture/module-boundaries.md
architecture/service-extraction-plan.md
modules/<module>/module-contract.md
AGENTS.md
```

Suggested `AGENTS.md` section:

```md
## Structure Architecture Rules

Before adding or moving production code, read:

- `architecture/design.md`
- `architecture/structure-contract.md`
- `architecture/module-boundaries.md`

Follow the structure contract as binding project architecture.

Rules:
- Do not create new top-level folders without updating `architecture/structure-contract.md`.
- Do not import another module's internal files directly.
- Import feature modules only through their public `index.ts` or documented contracts.
- Keep domain code independent from frameworks, databases, HTTP, UI, queues, and external APIs.
- Place new code according to the File Placement Rules in the structure contract.
- If the structure contract and implementation conflict, stop and propose a contract update before continuing.
- Design major modules as future service candidates, but do not introduce microservices without clear operational justification.
```

---

## Anti-patterns to Avoid

Avoid:

```txt
- global utils dumping ground
- flat MVC for a growing domain
- god service classes
- domain code importing database clients
- feature modules importing other modules' private files
- shared folder containing feature business logic
- two modules owning the same data
- premature microservices
- abstractions before variation exists
- folders named by vague technical roles only
- changing structure without updating the contract
- moving files without updating imports and boundary tests
```

---

## Decision Heuristics

Use these heuristics:

```txt
If it changes with one feature, keep it in that feature module.
If it is a stable primitive used by many modules, put it in shared.
If it talks to the outside world, put it in infrastructure or interface.
If it is a business invariant, put it in domain.
If it orchestrates a user or system action, put it in application.
If another module needs it, expose it through index.ts or contracts.
If it could become a service, document its data ownership and integration contracts.
If it has no clear responsibility, do not create the folder.
```

---

## Final Behavior Rules

Always prefer:
- explicit boundaries over clever shortcuts
- public APIs over internal imports
- module ownership over global buckets
- stable contracts over accidental coupling
- simple modular monolith before microservices
- staged migration over big-bang rewrites
- documented tradeoffs over silent assumptions

When uncertain:
- state assumptions
- choose the simpler structure
- preserve future extraction paths
- avoid premature abstraction
- document what would trigger a structure change later
