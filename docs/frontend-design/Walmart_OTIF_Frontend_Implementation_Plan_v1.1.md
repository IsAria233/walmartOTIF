# Walmart OTIF — Frontend Implementation Plan v1.1

## Status and design baseline

- Approved implementation plan, following the Business-First UI Demo v2.
- The HTML demo is the visual/layout reference, not backend behavior or API contract.
- Base implementation on the team's current `origin/main`, after inspection.
- Scope: frontend owned primarily by the user, subject to the existing team/Jira boundaries. Do not implement unassigned backend features.
- Framework: React, Vite, React Router, JavaScript, native Fetch with centralized API client and lightweight authentication state. No Redux or additional UI framework by default.
- Required deployment: Docker and Nginx (see SCRUM-43 and the group requirements).

## Five phases

### Phase 1 — Foundation & Authentication

- Scaffold the frontend in the existing `frontend/` directory after inspecting its current contents.
- React/Vite entry point, React Router, app shell, sidebar and top bar based on Demo v2.
- JWT login, `/me` identity check, logout, protected routes, role-aware navigation and forbidden-route redirects.
- Centralized API client, authenticated requests, known error handling.
- Docker/Nginx configuration for production assets, SPA deep links, and gateway API routing.
- Placeholder routes only for Investigations, Fine Records, and Case Workspace; **no Phase 2–4 business functionality yet**.
- Verify app launch/build, authentication/role/routing tests, and deployment configuration.
- Jira: SCRUM-43 and SCRUM-44.

### Phase 2 — Investigation Queue & Fine Records

- Case list with supported server-side filters, stable sorting, pagination, status and detail links.
- Fine Records list/details and associated Case links based on actual Domain APIs.
- Loading, empty and error states.
- Verify UI behavior, actual backend contracts and regression tests.

### Phase 3 — Case Workspace & Agent

- Case overview, Agent start/reinvestigation (only when supported), execution state, Findings, Evidence, handoff display.
- Evidence citations open the corresponding record/details.
- Do not invent live progress, SSE, WebSocket, percent-complete, or unsupported run-discovery APIs.
- Verify API states, findings/evidence display, errors and regressions.
- **First consolidated user acceptance review (UI/UX).**

### Phase 4 — Evaluation & Approval

- Calculation and amount comparison, Associate/Manager approval entry, required rejection reason, outcome and decision history.
- Role-aware controls, duplicate-submit protection, refresh after decisions, separate Agent resume handling.
- Manager pathway for high-value reversals, aligned to SCRUM-47 and actual backend role/threshold policy.
- Verify permissions, decision statuses, errors, resume and regression tests.

### Phase 5 — Integration & Final Verification

- Integrate React UI with current Gateway, Auth, Domain and Agent services.
- Validate Docker Compose and Nginx routing, core POC user journey and documentation.
- Run build, automated tests, supported integration/E2E tests, and realistic demo scenarios.
- Report external blockers explicitly; do not change other team services without approval.
- **Second consolidated user acceptance review (end-to-end).**

## Jira alignment

- SCRUM-12: Frontend epic for associates, managers, DC operations viewers.
- SCRUM-43: React app, React Router, Docker, Nginx, JWT API client and role route guards.
- SCRUM-44: Login, role-aware navigation, loading/success/error states and forbidden-route redirects.
- SCRUM-45: Investigation queue and Agent start/follow workflow; use supported status capabilities without inventing realtime progress.
- SCRUM-46: Fine/line, cited evidence, ruled-out causes, confidence, recomputed fine, approve/reject, required reject reason.
- SCRUM-47: Manager approval of high-value reversal and repeated DC failures; use actual backend workflows, flag any unavailable APIs.
- SCRUM-49: Docker Compose full-stack integration is a separate team deployment ticket; frontend must supply its Docker/Nginx pieces, not take over all infrastructure.

## Development protocol

1. Implement **only the current phase**. Do not add optional features or other members' work.
2. For each phase, Codex performs implementation, lint/build, relevant automated tests, API contract checks, and regression tests.
3. On failure, Codex diagnoses, fixes and reruns checks autonomously within phase scope; report blockers, skips and unverified checks truthfully.
4. Do not shift ordinary debugging and repeated testing to the user; two consolidated manual acceptance checkpoints after Phases 3 and 5, with optional user spot-checks.
5. User's ordinary questions and hypothetical scenarios **do not** alter the plan. Change scope only on explicit instruction.
6. Preserve existing branches, worktrees and unrelated modifications. Do not commit, push, merge, or create PRs without explicit permission.
7. The demo uses fictional presentation data; the production frontend must respect actual API types, auth roles, backend behavior, and security boundaries.

## Exclusions unless explicitly approved

- Analytics dashboard, bulk approvals, upload system, registration, token refresh, policy/user management, notification system, live streaming and unassigned backend development.
- Do not assume dedicated run-discovery APIs, complete audit-log APIs or comprehensive approval-stage queue APIs exist.

## Acceptance context

The group requirements specify React, React Router, JavaScript/TypeScript, Docker, Nginx, role-aware access, agent interaction, approvals, and user-visible loading/success/error states. The fixed plan addresses these within its phased POC scope.
