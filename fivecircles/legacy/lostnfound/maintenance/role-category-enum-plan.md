## Role/Category Enum & Dynamic Role Lifecycle Plan

### 1) Required Enums (authoritative from spec)
- Lost/Found category: `ELECTRONICS, WALLET, ID_CARD, BOOK, CLOTHES, ETC`
  - ETC: allow free-text user input stored alongside `category=ETC` (e.g., `categoryEtcLabel`).
- StorageType: `SELF, OFFICE, SECURITY, LOCKER`
- Handover method (already): `MEET, OFFICE, COURIER`

### 2) Auth/User role rules
- Base roles allowed at any time: `LOSER, FINDER` (others are privileged).
- Registration UI: must pick LOSER or FINDER (single select for now).
- Dynamic dual-role:
  - If a LOSER registers a Found → they must have FINDER; add FINDER to roles.
  - If a FINDER registers a Lost → they must have LOSER; add LOSER to roles.
  - Both roles may coexist.
- Role removal:
  - When a Lost is deleted/closed OR associated handover completes, LOSER can be removed if no other active losts.
  - When a Found is discarded/handed over OR deleted, FINDER can be removed if no other active founds.
  - Admin/Office/Security/Courier roles persist (manual assignment only).
- MyPage: user can remove/add LOSER/FINDER if business rules allow (no active items blocking removal).

### 3) Backend enforcement plan
- Auth service:
  - `RegisterRequest.role` → enum `LOSER | FINDER` (validate @NotNull).
  - Store roles as a collection (user_roles table) instead of single field, or persist a comma-separated list minimally for now.
  - Login token must include all active roles for the user.
- Lost service:
  - DTOs use enum for `category`.
  - If `category == ETC`, accept optional `categoryEtcLabel` string.
  - On Lost create: ensure requester has LOSER; if not, auto-attach LOSER via auth call (or fail with 403 if not allowed).
  - On Lost delete/close: if no other active losts, allow LOSER removal (via auth call).
- Found service:
  - DTOs use enum for `category`, `storageType`.
  - `categoryEtcLabel` for ETC.
  - On Found create: ensure requester has FINDER; if not, auto-attach FINDER via auth call (or 403).
  - On Found discard/hand-over: if no other active founds, allow FINDER removal (via auth call).

### 4) Frontend alignment
- Lost/Found create/edit forms:
  - Category select fixed to enum list.
  - If ETC chosen, show free-text input stored as `categoryEtcLabel`.
  - StorageType select uses enum list.
- Login/register:
  - Register form: single select (LOSER | FINDER) to start.
  - MyPage: allow toggle for LOSER/FINDER if backend permits (show blocking message when active items exist).

### 5) Validation/HTTP behavior
- DTOs: `@NotNull/@NotBlank` on enums; invalid enum → 400.
- ETC free-text is optional; only stored when category=ETC.
- Fail open vs. closed: default fail closed (reject create if role missing) unless auto-attach is implemented.

### 6) Execution steps (high level)
1. Auth: introduce role enum + role storage (multi-role) + validation.
2. Lost/Found DTOs to enums + ETC free-text.
3. Role checks on create/delete with optional auto-attach (LOSER/FINDER).
4. Frontend selects aligned to enums; ETC label input; MyPage role toggle UX.

### 7) Notes
- Need a small user_roles table (user_id, role) or array field; adjust token claims accordingly.
- If schema change is heavy, temporary approach: store roles as comma-separated string but validate against enum; MyPage edits that string safely.
