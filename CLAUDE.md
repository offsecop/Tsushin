- We have a containers architecture, so always update the code, restart/rebuild the containers when applicable, no need to delegate this task to the user. Never run the app directly (outside the container environment).
- When making changes to the frontend, make sure you rebuild the container without cache so that we don't load the old code once and get into a troubleshoot rabbit hole unnecessarily.
- **Safe Container Rebuild (CRITICAL):** MCP containers (WhatsApp bots, tester, toolbox) share `tsushin-network` with the compose stack. **NEVER use `docker-compose down`** for routine rebuilds — it tears down the network and kills WhatsApp sessions (WebSocket drops → QR re-auth loop). Instead:
  ```bash
  # SAFE — rebuilds only the target service, network stays intact
  cd /Users/vinicios/code/tsushin && docker-compose up -d --build --no-cache backend
  cd /Users/vinicios/code/tsushin && docker-compose up -d --build --no-cache frontend
  # Both at once:
  cd /Users/vinicios/code/tsushin && docker-compose up -d --build --no-cache backend frontend

  # DANGEROUS — tears down network, kills WhatsApp sessions
  docker-compose down && docker-compose up -d  # ← NEVER for routine rebuilds
  ```
  Only use `docker-compose down` when you explicitly need to recreate the network or start fresh (and are willing to re-authenticate WhatsApp).
- Remember that our solution is multi-tenant, so for things that are tenant-based, we need to specify the "tenantid".
- Anything you implement must be tested, if it's backend, programmatically, if it's UI using your browser automation.
- Make sure you commit/push the code to GitHub after every significant implementation so that we can have code change traceability and can rollback problems if needed.
- **Git Identity:** Always commit and push as `iamveene`. Before committing, ensure the repo-level git config is set:
  ```bash
  git -C /Users/vinicios/code/tsushin config user.name "iamveene"
  git -C /Users/vinicios/code/tsushin config user.email "iamveene@users.noreply.github.com"
  ```
  **No co-authorship lines.** Never add `Co-Authored-By`, `Co-authored-by`, or any similar trailer to commit messages. All commits must appear as solely authored by `iamveene` — no Claude, no Cursor, no AI co-author attribution whatsoever.
- Don't bother generating a fix summary if you still did not fix and confirm the problem. Summaries are for the end, after you confirmed, tested, validated the fix with proven evidence.
- Bot acceptable tests are via WhatsApp tester MCP or playground using browser automation (general), you have access to both and can proactively test everything, so don't be lazy and delegate simple tests to the user.
- **Seed/Installer Script Maintenance:** Whenever implementing architectural changes, DB schema modifications, or new functionality, always review and update the seed/installer scripts (e.g., `backend/services/tone_preset_seeding.py`, database initialization scripts) to ensure they remain consistent with the new changes. This includes: new tables, new required fields, default values, enum changes, and any data that needs to be pre-populated.

# Branching Strategy (Git Flow Lite)

- **`main`** — stable releases only. Tagged with version numbers (e.g., `v1.5.0`). Never push directly to `main`; merge via PR only.
- **`develop`** — active development branch. This is the default working branch for new features.
- **`feature/*`** — feature branches created from `develop` (e.g., `feature/websocket-streaming`). Merge back to `develop` when complete.
- **`release/X.Y.x`** — hotfix branches created from a release tag if a patch is needed on a shipped version. Merge to both `main` and `develop`.
- Always work on `develop` or a `feature/*` branch. Never commit directly to `main`.
- When a version is ready to ship: merge `develop` → `main` via PR, then tag the new version on `main`.
- Hotfix workflow: `git checkout v1.5.0 && git checkout -b release/1.5.1` → fix → merge to `main` + `develop`.

# Docker & Worktrees - CRITICAL

**ALWAYS start Docker containers from the main repository, never from worktrees.**

```bash
# CORRECT - always use this:
cd /Users/vinicios/code/tsushin && docker-compose up -d

# WRONG - never do this from a worktree:
cd /Users/vinicios/.claude-worktrees/tsushin/<worktree-name> && docker-compose up -d
```

**Why:** Each worktree has its own empty `backend/data/` directory. Starting Docker from a worktree mounts that empty directory, causing all app data (users, agents, flows, messages, memory, etc.) to appear missing. The actual data lives in `/Users/vinicios/code/tsushin/backend/data/`.

**Note:** PostgreSQL relational data is stored in the `tsushin-postgres-data` Docker named volume and is unaffected by worktree directory. Only ChromaDB vectors and MCP instance data in `backend/data/` are at risk from worktree starts.

**If you accidentally started from a worktree:**
```bash
docker stop tsushin-backend tsushin-frontend
docker rm tsushin-backend tsushin-frontend
cd /Users/vinicios/code/tsushin && docker-compose up -d
```

**Rebuilding containers safely (preserve MCP/WhatsApp sessions):**
```bash
# SAFE — rebuild specific services without network disruption
cd /Users/vinicios/code/tsushin && docker-compose up -d --build --no-cache backend
cd /Users/vinicios/code/tsushin && docker-compose up -d --build --no-cache frontend

# UNSAFE — docker-compose down tears down tsushin-network, killing WhatsApp WebSocket sessions
# Only use when you explicitly need to recreate the network and are willing to re-auth WhatsApp
```

# Strategic and Sensitive File Management

- All strategic planning documents (roadmaps, future implementations, business plans) must be stored in the `.private/` folder, which is gitignored and never pushed to the repository.

- Files that should go in `.private/`:
  - ROADMAP.md, ROADMAP_*.md (future implementation plans)
  - STRATEGIC_*.md, BUSINESS_*.md (business strategy documents)
  - COMPETITIVE_*.md (competitive analysis with sensitive info)
  - Any document containing API keys, credentials, or sensitive configuration
  - Personal notes, internal meeting notes, or proprietary information
  - Backup .env files or configuration with real credentials

- The `.private/` folder structure:
  - `.private/ROADMAP.md` - Main strategic roadmap
  - `.private/STRATEGIC_PLANS.md` - Business strategy
  - `.private/MY_DATA_BACKUP/` - Backups of sensitive data
  - `.private/*.env*` - Environment files with real credentials

- Before creating strategic documents, always check if they contain sensitive information. If yes, create them in `.private/` instead of the root or docs/ folder.

- After finishing any fix/improvement/implementation with validation, commit the changes to git so that we can track changes and easily rollback if things go wrong.

- Verify `.private/` is in `.gitignore` (it should be at line 111 with pattern `.private/`).

- Public documentation (README.md, ARCHITECTURE.md, guides in docs/) can remain in the repository, but future-facing strategic content should be private.

- If you're asked to create a roadmap or strategic plan, default to creating it in `.private/` unless explicitly told to make it public.

🧪 Test Users (Dev Mode)

Tenant Owner
test@example.com
test123

Global Admin
testadmin@example.com
admin123

Member
member@example.com
member123

# Public API v1 — Regression Testing

**API Base URL:** `http://localhost:8081/api/v1/`

**Regression Test API Client** (seeded, `api_owner` role, 120 RPM):
- Credentials stored in `.env` as `TSN_API_CLIENT_ID` and `TSN_API_CLIENT_SECRET`
- Use for automated regression tests instead of UI login for basic agent communication

**Quick API Test (Direct Mode):**
```bash
# List agents
curl -H "X-API-Key: $TSN_API_CLIENT_SECRET" http://localhost:8081/api/v1/agents

# Chat with agent (sync)
curl -X POST -H "X-API-Key: $TSN_API_CLIENT_SECRET" \
  -H "Content-Type: application/json" \
  http://localhost:8081/api/v1/agents/1/chat \
  -d '{"message": "Hello, respond briefly."}'

# OAuth2 token exchange
curl -X POST http://localhost:8081/api/v1/oauth/token \
  -d "grant_type=client_credentials&client_id=$TSN_API_CLIENT_ID&client_secret=$TSN_API_CLIENT_SECRET"
```

**Available API Endpoints:**
- `GET /api/v1/agents` — List agents (paginated)
- `GET /api/v1/agents/{id}` — Agent detail
- `POST /api/v1/agents` — Create agent
- `PUT /api/v1/agents/{id}` — Update agent
- `DELETE /api/v1/agents/{id}` — Delete agent
- `POST /api/v1/agents/{id}/chat` — Chat (sync default, `?async=true` for queue)
- `GET /api/v1/queue/{id}` — Poll async queue
- `GET /api/v1/skills` — List skills
- `GET /api/v1/tools` — List sandboxed tools
- `GET /api/v1/personas` — List personas
- `GET /api/v1/tone-presets` — List tone presets
- `GET /api/v1/security-profiles` — List security profiles

# WhatsApp Channel Tests

**Instance Setup:**
- Agent/bot instance: +5527988290533 (mcp-agent-tenant..., port 8080)
- Tester instance: +5527999616279 (tester-mcp, port 8088)

**Testing Guidelines:**
- Tester should only initiate conversations with the agent/bot during QA/Tests, not the other way around
- Keep tests strict between those two contacts only
- Use tester MCP API to send test messages:
  ```bash
  curl -X POST http://localhost:8088/api/send \
    -H "Authorization: Bearer <api_secret>" \
    -H "Content-Type: application/json" \
    -d '{"recipient": "5527988290533", "message": "<test_command>"}'
  ```

**WhatsApp Session Health:**
- WhatsApp sessions can drop if `tsushin-network` is disrupted (e.g., by `docker-compose down`)
- Always check session health before WhatsApp tests: `docker logs mcp-agent-tenant_20251202232822_1766790203 --tail=10` — look for QR code loops (session expired) or normal message handling (session active)
- If session is expired, restart the container: `docker restart mcp-agent-tenant_20251202232822_1766790203` — then re-scan QR from the linked phone
- **Prevention:** Never use `docker-compose down` for routine rebuilds; use `docker-compose up -d --build --no-cache <service>` instead

**WhatsApp Round-Trip Verification (for regression tests):**
1. Send message via tester: `curl -X POST http://localhost:8088/api/send ...`
2. Verify tester sent: check `docker logs tester-mcp --tail=5` for `Message sent true`
3. Verify agent bot received: check `docker logs mcp-agent-tenant_... --tail=10` for `STORAGE SUCCESS`
4. Wait 30-60s for LLM processing + conversation delay
5. Verify bot responded: check tester logs for incoming message from bot (the `←` arrow entries from the bot's LID number)
6. If no response, check backend: `docker compose logs --tail=20 backend | grep -E "generate|gemini|send"`

**Sandboxed Tool Command Format:**
- Use `/tool <tool_name> <command_name> param=value` format
- Example: `/tool nmap quick_scan target=scanme.nmap.org`
- Example: `/tool dig lookup domain=google.com`
- Flags like `--target` are NOT supported; use `param=value` syntax instead

# Pre-commit Hooks

- Pre-commit hooks are installed to prevent secrets from being pushed to the repository
- Run `./scripts/setup-hooks.sh` to install hooks (one-time setup)
- If a commit is blocked, check the output for the detected secret pattern
- Add legitimate patterns (placeholders, test values) to `.gitleaks.toml` allowlist if needed
- Never use `--no-verify` to bypass hooks without explicit user approval
- When creating test files, use obvious fake values like `test-key-12345` or `fake-api-key`
- The CI workflow (`.github/workflows/security.yml`) also scans for secrets on push/PR

# Test Scripts & Development Files

**Always save test scripts and development files in `backend/dev_tests/`** - this directory is gitignored and will not be pushed to the repository.

- All `test_*.py` files should go in `backend/dev_tests/`
- All `run_*.py` utility scripts should go in `backend/dev_tests/`
- Manual testing scripts, debugging utilities, and one-off test files belong here
- This keeps the repository clean and prevents accidental exposure of test credentials

**Exception:** Proper pytest unit/integration tests should remain in `backend/tests/` as they are needed for CI/CD.

The `.gitignore` patterns prevent accidental commits of test files outside their designated locations:
- `backend/dev_tests/` - Development test scripts (gitignored)
- `backend/test_*.py` - Blocked at root level
- `backend/run_*.py` - Blocked at root level
- `backend/scripts/test_*.py` - Blocked in scripts folder

# Regression Testing Methodology

**When to run full regression:** After major refactoring, DB migrations, Docker config changes, multi-area modifications, or before release merges to main. Use `/fire_full_regression`.

**Rebuild before regression:**
```bash
# ALWAYS use safe rebuild — preserves MCP/WhatsApp sessions
cd /Users/vinicios/code/tsushin && docker-compose up -d --build --no-cache backend frontend
```

**Pre-flight checks before regression:**
1. All compose containers healthy: `docker compose ps`
2. MCP containers running: `docker ps --filter name=mcp --filter name=toolbox`
3. WhatsApp session active (no QR loops): `docker logs mcp-agent-tenant_20251202232822_1766790203 --tail=10`
4. If WhatsApp session expired: `docker restart mcp-agent-tenant_20251202232822_1766790203` + re-scan QR

**Regression test coverage (minimum):**
1. Infrastructure: /api/health, /api/readiness, /metrics
2. Auth: tenant login, admin login, API v1 OAuth2
3. API sweep: all tenant/admin/v1 endpoints return 200
4. API v1 E2E: `test_api_v1_e2e.py` (28 tests)
5. Browser: login, dashboard, agents, playground (send message + verify response), flows, hub, settings (all subpages), system admin
6. Sandboxed tools: `/tool dig lookup domain=example.com` via API chat
7. WhatsApp round-trip: send via tester → verify bot receives → verify bot responds → verify tester receives response
8. Log review: 0 backend errors, 0 frontend errors (known `sharp` warning excluded)

**WhatsApp round-trip is mandatory** — if the session is down, fix it before marking regression as passed. A partial "message sent but no response" is NOT a pass.
