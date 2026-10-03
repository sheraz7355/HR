# Development Policies

## 0. Edit Fallback
If the edit tool fails or reports an error on a change (root cause on this machine: the folder was renamed from `Open Code\HR` to `accountix_erp` but opencode's sqlite state still held the old path, so permission/form endpoints 500'd on realPath ENOENT and every edit that needed a permission ask died instantly; fixed by repointing `project`/`project_directory`/`worktree`/`session` rows to the new path — keep that consistent if renaming again), retry the change with python tools/apply_edit.py <file> --old <exact text> --new <replacement> (add --replace-all only when every occurrence must change; use --old-file/--new-file for long blocks). It verifies uniqueness before writing and exits non-zero with a message on failure. Never silently skip a change; verify the file on disk afterwards.

## 1. Change Impact Assessment
When any new update is made, ensure all other actions/features connected to it are updated accordingly. Check for side effects before closing a change.

## 2. E2E Test Coverage
Every change must be covered by updated E2E tests. Run the full E2E suite before committing. Add new tests for any new functionality or UI flow.

## 3. Responsive UI
All UI must be responsive and optimized for mobile use. Every module must render correctly on small screens (320px+). Test on mobile viewport before marking complete.

## 4. E2E for All App Modules
E2E tests must cover all app modules:
- **Inventory**: Login, Dashboard, Products, Suppliers, Customers, Purchase Invoice (form, add/clear items, pill toggles, calculations, global inputs), Purchase Return, Logout
- **HR**: Login, Hub, Dashboard, Attendance, Leave, ESS, Profile, Logout

## Session Summary (Oct 2026) — Document-Date Posting, Date-Ordered Costing, Books Integrity

### Objective
Make every module post accurately in real-world sequences: back-dated documents, edits (unapprove → change → re-approve), deletions/reversals and returns — with inventory costing, the general ledger, sub-ledgers and reports all staying tied. Add label-wise tracking to the remaining cost-bearing documents and distinctive reports.

### Completed
- **Documents post on their own date** (journal AND stock): sales/purchase invoices (the forms showed a date but never sent it; the server never saved it), sales/purchase returns, consumption/scrap/adjustment/stock-take vouchers (new date field), FA capitalisation / asset→inventory transfers (`asset_transfers.transfer_date`), FA disposal (`disposal_date`, depreciates to that date first), payroll (last day of the payroll month). The period lock now refuses back-dated documents in closed periods. `shared/posting_helpers.parse_doc_date`
- **Date-ordered costing** (`shared/costing.py`): `stock_ledger.txn_date`; layers consumed in (txn_date, id) order. A back-dated receipt/issue, or the reversal of an earlier document, replays the product's history (`_replay`): earlier rows frozen, later issues re-costed. Back-dated issues are refused if stock wasn't on hand AT THEIR DATE or if they'd strip a later issue. Sales returns follow their re-costed sale; purchase returns draw from their own invoice's layers (`prefer=`).
- **Re-costing hits the GL** (`shared/cost_adjustment.py`): every moved cost gets a `StockCostAdjustment` + journal `CADJ-<type>`/`<voucher id>` charging the difference to the account the issue originally hit (COGS on the line's label, consumption/scrap charge account, adjustment account, asset), dated in the issue's period or today if closed. Reversing a voucher un-posts its own CADJ journals. The old VAR/variance write-off path is gone (it produced wrong P&L on edit flows).
- **Bugs fixed**: approved inventory vouchers could be re-submitted and posted twice; stock-take journal sat under the take so unapproving its adjustment left the GL posted; purchase return credited inventory with a tax-inclusive value and never reversed input tax / WHT (now cost + tax + WHT + price-difference); returns trusted the browser's max-returnable qty (server cap now); invoices with approved returns could be unapproved; inventory→FA transfer credited inventory at a typed price without moving stock (now through costing); product opening stock / bulk import / quick adjust changed only the display column (now cost layer + journal: `shared/stock_entry.py`); products with stock history could be deleted; payroll "Replace All" left the old journal posted (double expense) and didn't restore loan balances; payroll preview hard-coded to Jul 2026; JSON saves refused by the period lock got a redirect instead of a JSON error; debug banner on the consumption form; ST reference via count()+1 collided after deletes; dashboard stock value used qty × rounded avg.
- **Labels**: per-line label splits for SI revenue/discount/charges and exact COGS per line label; PI inventory split by landed cost per label; label on consumption/scrap/adjustment vouchers and fixed assets (acquisition + depreciation lines).
- **New reports**: Executive → **Books Integrity** (`shared/integrity.py`: TB, every journal, inventory GL = stock valuation, layers, quantities, asset register = GL, approved docs = posted journals, recent re-costings); Finance → **P&L by Label** (labels as columns + Unlabelled = company total); Inventory → **Stock Valuation** as of any date with opening/in/out/closing and GL reconciliation; product ledger/stock ledger in document-date order with re-costing history.
- **Audit log** (`shared/audit.py`, `shared/models/audit_log.py`): a session hook records every create / edit (field-level old→new) / delete / approve / unapprove of tracked business records and every journal post / un-post, with user, time (UTC), IP and path — across all modules, no per-route code. `record_now()` adds sign-in, failed sign-in, sign-out and refused postings (e.g. into a closed period) on its own connection so they survive the rollback. Secrets (password hashes, tokens) are redacted. `audit_logs` is in `tenancy.GLOBAL_TABLES` (platform events have no company) and every reader filters explicitly. Viewers: Settings → Administration → **Audit Log** (company admins: filters, field diffs, CSV export at `/settings/audit-log.csv`) and Super Admin → **Audit** (all companies + platform events). No route edits or deletes audit rows. Tests: `tests/e2e/test_audit_log.py` (7). After the audit hook: full E2E **726 passed**, plus 2 Playwright timeouts that occurred while the unit suite ran in parallel and passed on re-run (8/8 in their classes); unit **447 passed**
- **UI**: voucher forms reworked (date + label, read-only once approved, POST unapprove/delete, responsive tables); verified no horizontal scroll at 360px on the new/changed pages.

### Verification
- Unit: 439 + 8 new (`tests/unit/test_costing_backdated.py` 17, `test_posting_helpers.py` 8; variance tests in `test_costing.py` rewritten for re-cost semantics)
- New E2E `tests/e2e/test_books_integrity.py` (20 steps, one fresh company, real routes, integrity checks after each): back-dated purchase/sale, refused back-dated sale, purchase price correction, sales/purchase return, over-return refusal, middle-sale reversal + delete, approved-voucher re-submit, closed period, capitalisation, opening stock, quick adjustment, product delete guard, payroll replace, multi-label invoice, reports render
- Full E2E run: **715 passed, 0 failed**; the late-touched files (books integrity, inventory, routes smoke, input hardening, HR, fixed assets) re-run after the final edits: **346 passed**. Unit: **447 passed**

### Key Files
`shared/costing.py`, `shared/cost_adjustment.py`, `shared/integrity.py`, `shared/posting_helpers.py`, `shared/stock_entry.py`, `invoicing_app/routes/{invoices,purchase_invoice,sales_return,purchase_return}.py`, `inventory_app/routes/{vouchers,transfers,products,reports}.py`, `fixed_assets_app/routes/{transfers,assets,depreciation}.py`, `hr_app/routes/compensation.py`, `executive_app/templates/executive/integrity.html`, `finance_app/templates/finance/label_pl.html`, `inventory_app/templates/reports/valuation.html`, `app.py` (migrations: `stock_ledger.txn_date` + backfill, label/date columns)

## Session Summary (Aug 2026) — Silent-Approve Bug Fix + E2E Flake Family Root-Caused

### Objective
Fix the silent-approve loophole found during browser verification of the executive dashboard (a `save_approve` action string posted a JV without actually approving it — so Unapprove → Approve was needed to post), and root-cause the recurring Playwright "timing flake" family that kept failing a handful of E2E tests only on full-suite runs.

### Completed
- **Silent-approve fix** (`finance_app/routes/accounting.py::voucher_form`):
  - The form posted `action=save_approve` but the handler branched on `action == "approve"` — an unknown action silently became a bare save, marking the voucher Approved without posting lines. Now `save_approve` **approves and posts** (same path as `approve`), `save` stays a bare save, and any other action string falls back to a bare save
  - `approved_at`/`approving_user_id` set in the same branch as the posting so approval and posting can never diverge again
- **Regression tests** (`tests/e2e/test_accounting_voucher_form.py` *(new)*, 3 tests): bare `save` keeps the voucher unapproved, `approve` is the only path to the ledger (lines posted exactly once, status Approved), and the action string round-trips through the form without leaking. Verified red → green: the tests fail against the pre-fix handler
- **E2E flake family — root cause** (`tests/e2e/conftest.py::flask_server`):
  - The readiness check just connected to port 5000. **Any leftover dev/test server already listening** made it "ready" instantly while the spawned `run_local.py` died with "Address already in use" — so the whole Playwright suite silently ran against the wrong database (a stale `erp_dev.db`) → state-dependent tests (`test_voucher_ui` mobile layout, `test_invoice_designs` freight) failed on full runs but passed in isolation. Root-cause confirmed live: two reloader parents (`app.py` + `run_local.py`) were fighting over port 5000 for hours, respawning their children
  - Fix 1 — **port ownership pre-check**: `_assert_port_free()` binds port 5000 before spawning; if it is taken, the fixture fails fast with a message naming the holder instead of silently testing the wrong DB
  - Fix 2 — **subprocess-alive check**: after the readiness loop, `proc.poll() is None` must hold; a server that died during startup raises with the log tail
  - Fix 3 — **fresh DB per run**: the fixed `sqlite:///e2e_test.db` accumulated rows across sessions, making "empty state" assertions flaky; each session now gets a `NamedTemporaryFile` db, deleted in `finally`
- **Environment cleanup**: killed 5 stale `python.exe` server processes (three `run_local.py` reloader leftovers from previous sessions + the `app.py` pair started during this session's verification); port 5000 verified free afterwards

### Verification (this session)
- New voucher-form tests: 3 passed in isolation; 56 passed for the targeted group (voucher UI + invoice designs + executive reports + voucher form)
- **Full E2E suite: 580 passed, 0 failed** (previous: 568 passed + 2 flake failures) — the flake family is gone; ran with leftover servers killed and the hardened fixture
- Unit suite: **281 passed**
- Port 5000 free after the suite (fixture terminates its server in `finally`)

### Key Files
- `finance_app/routes/accounting.py` — `save_approve` now approves and posts; approval fields set with the posting
- `tests/e2e/test_accounting_voucher_form.py` *(new)* — 3 regression tests
- `tests/e2e/conftest.py` — `_assert_port_free()`, subprocess-alive check, per-run temp DB

## Session Summary (Aug 2026) — Executive Dashboard: Net Assets, Ratios, Aging & Exposures

### Objective
Turn the Executive Reports dashboard into a real-time business snapshot: net assets derived straight off the chart, current/quick ratios, and FIFO-aged receivables and payables — weighted-average collection/payment days, oldest debt, aging-profile buckets, and the largest exposures — all computed from posted journal lines with nothing stored.

### Completed
- **FIFO aging engine** (`shared/executive_reports.py::aging`, `_age_party`, `_aging_side`):
  - Ages every open in-scope balance from its posting layers: on receivables, debits build the stack and credits consume the **oldest layer first**; payables mirror it. A payment pulls the oldest debt down first, so a party that received 1,000 forty-five days ago and 400 five days ago is aged as 600 @ 45 days
  - Returns per side: total, party count, **weighted-average days** (weighted by surviving balance), **oldest days + party**, the four buckets (Current / 31–60 / 61–90 / 90+), and the **top 5 parties with % share**; `as_of` filters postings and re-ages to that day (future-dated layers clamp to 0 days)
- **Liquidity snapshot** (`shared/executive_reports.py::liquidity`):
  - Company-wide (whole chart, available even with no selection): net assets (assets − liabilities), total/current assets, current liabilities, inventory, **current ratio** and **quick ratio**. Current Assets / Current Liabilities are located by their standard names at level 2, inventory by the Inventories subtree; contra accounts (accumulated depreciation) net themselves out as plain balances
  - Ratios render only when current liabilities > 0 — a negative "liability" balance (overpaid, drifted payroll) is really an asset, so the cards show "—" instead of a meaningless negative number
- **Dashboard** (`executive_app/templates/executive/dashboard.html`, `_style.html`, route in `executive_app/routes/reports.py`):
  - New **KPI row** (always visible): Net assets, Current ratio, Quick ratio (green ≥1.5 / ≥1, red <1), Avg collection days, Avg payment days, Oldest receivable/payable (days + party name)
  - **Aging profile** chart: CSS-only horizontal bars (no chart library) with receivable (green) vs payable (amber) per bucket, amounts and a legend
  - **Largest exposures** card: top 5 per side with share bars, each row linking to the party ledger
  - Responsive: KPI grid auto-fits (2 cols @360px, 140px min), charts stack to one column, no horizontal scroll at 320px+

### Verification (this session)
- 8 new E2E tests in `tests/e2e/test_executive_reports.py` (**32 passed** in the file): FIFO aging math (45d layer + 5d receipt → 600@45, oldest-first consumption), bucket shares, top-party order, empty-selection and as-of behaviors, liquidity deltas on a real cash posting (current assets / net assets / total assets +500, inventory untouched), ratio formulas, and dashboard rendering with all KPI labels + party names
- Full suite: **281 unit + 568 E2E passed**; 2 unrelated flake failures (`test_voucher_ui` mobile layout, `test_invoice_designs` freight) pass in isolation — known Playwright timing-flake family
- Manually verified in the browser against the live dev server: dashboard with real posted vouchers (5,000 receivable @ 45 days, 2,000 payable @ 5 days → correct buckets/avg/oldest), mobile 360px/342px emulation with zero horizontal overflow; settings picker and JV voucher flow exercised end-to-end (a `save_approve` action string silently sets `status=approved` without posting — used Unapprove→Approve to post correctly)

### Key Files
- `shared/executive_reports.py` — `aging()`, `_age_party()`, `_aging_side()`, `liquidity()`, `BUCKET_DEFS`
- `executive_app/routes/reports.py` — dashboard route passes `recv_age`, `pay_age`, `liq`
- `executive_app/templates/executive/dashboard.html` — KPI cards + aging/exposure charts
- `executive_app/templates/executive/_style.html` — `.exr-kpis`, `.exr-charts`, `.exr-bar-*`, `.exr-top-*` (+ ≤480px tweaks)
- `tests/e2e/test_executive_reports.py` — 8 new aging/liquidity/dashboard tests

## Session Summary (Aug 2026) — Super Admin Console: Users, Quotas, Module Entitlement, Blocking

### Objective
Finish the super admin console so it actually governs the platform: it is the only door an account comes through, it sets per-user company quotas, it decides which modules a company has bought, and it can block one person from one company. Also close the hole in HR, which used to mint logins that belonged to no company.

### Completed
- **Manage Users** (`superadmin_app/routes.py::users`, `user_detail`, templates `users.html`, `user_detail.html` *(new)*):
  - `POST /superadmin/users/` creates an account — the only creation path outside the console's own company form. Placeholder `employee_code` (`SA####`) because `users.employee_code` is globally unique and NOT NULL; the real per-company code comes from HR
  - `/superadmin/users/<id>/` — password reset (min 4 chars), activate/deactivate with a self-deactivation guard, name, quota overrides, membership list
- **Per-user quotas** (`shared/models/base.py`, `shared/models/company.py::GlobalLimits`):
  - `User.max_companies_owned` / `max_companies_joined`, both nullable. `company_limit_for(user)` falls back to `GlobalLimits.max_companies_per_user`; `join_limit_for(user)` has no global default, so unset = unlimited
  - Enforced in `shared/routes/portal.py::create` (owned) and `shared/routes/settings.py::accept_invitation` (joined). Blank input writes NULL, never 0
- **Module entitlement** (`Company.MODULE_COLUMNS`, `module_enabled()`, `enabled_modules()`):
  - Seven `mod_*_enabled` columns, DEFAULT 1 so existing companies keep everything. NULL reads as enabled — a column added by migration must not switch a module off
  - `User.module_access` is now **entitlement AND user flag**. A company admin bypasses the user flag (that is what admin means) but never the entitlement. With no active company (portal/console) the user flag alone decides
  - Company edit form is the whole truth: an absent checkbox is a disabled module
- **Member blocking** (`CompanyMembership.BLOCKED`, `superadmin.member_block`): status flips ACTIVE↔BLOCKED, keeping role, employee code and history. Every gate already filters on ACTIVE, so a blocked member simply cannot enter. The route checks the membership belongs to the company in the URL (404 otherwise)
- **My Companies** (`superadmin.my_companies`, `my_companies.html` *(new)*): the super admin's own books — same slug rule as the portal, same `provision_company()`, Open Books goes through the shared `company_switch`
- **HR no longer creates logins** (`hr_app/routes/auth.py`): `/users/add` is **gone**, replaced by `/members/assign`. It lists active members of this company with no membership `employee_code` yet and gives them one plus designation/department/manager. Codes are unique **per company**, so EMP100 can exist in two companies. Nav and back-link map updated
- **`templates/access_denied.html`** *(new)*: the ~20 fixed-assets route guards render `"access_denied.html"`, which had no file at the root of the template loader — every refusal raised TemplateNotFound and became a 500. Latent before (only non-admins hit it); reachable for everyone once a company can lose a module
- **Console nav**: Manage Users / Manage Companies / My Companies / Platform (the global-limits page, otherwise only reachable via the brand link)
- **Schema migration** (`app.py::_migrate_schema`): seven `companies.mod_*_enabled BOOLEAN DEFAULT 1`, two `users.max_companies_*` INTEGER

### Verification (this session)
- New E2E `tests/e2e/test_superadmin_console.py` (**25 tests**): user creation + duplicate refusal + super-admin-only access, quota overrides both ways (set, then cleared back to the global default), join cap blocking and then admitting the same invitation, password/deactivation/self-guard, My Companies provisioning (chart > 50 accounts, ≥14 voucher series) + slug/duplicate refusal, module defaults + toggling + admin-is-not-exempt + hub tile and route guard, block/unblock round-trip preserving role and code + pending-membership refusal + cross-company 404, HR assign (per-company codes, same code in two companies, clash refused, non-member refused, `/auth/users/add` now 404)
- **Full suite: 716 passed, 0 failed** (281 unit + 435 E2E). No flakes this run

### Key Files
- `superadmin_app/routes.py` — users/user_detail/my_companies/member_block, module entitlement save
- `superadmin_app/templates/superadmin/{users,user_detail,my_companies,companies,company_edit,base}.html`
- `shared/models/base.py` — quota columns, `module_access` entitlement gate
- `shared/models/company.py` — `MODULE_COLUMNS`, `module_enabled`, `BLOCKED`, `company_limit_for`/`join_limit_for`
- `hr_app/routes/auth.py`, `hr_app/templates/auth/member_assign.html` *(new)* — Assign Member
- `templates/access_denied.html` *(new)* — module refusal page
- `tests/e2e/test_superadmin_console.py` *(new)*

## Session Summary (Aug 2026) — Company Portal + Tenancy Count-Scoping Fix

### Objective
Implement the multi-company workflow the user described: a global user logs in and lands on a portal showing (a) companies he created and (b) companies where other global users assigned him a role; clicking a company opens its books; a separate super admin portal controls all users and companies. Also fix a latent tenancy bug discovered while testing: aggregate/count queries were never tenant-filtered.

### Completed
- **User portal** (`shared/routes/portal.py`, `templates/portal/index.html`):
  - `GET /portal/` — lists owned companies, companies where the user has a role, pending invitations; create form with quota text; Super Admin Console link for super admins only; responsive, blue theme `#1d4ed8`
  - `POST /portal/create` — slug regex `^[a-z0-9][a-z0-9-]{1,60}$`, quota `owns_company_count() >= GlobalLimits.get().max_companies_per_user`, creator auto-membership `Role.ADMIN`, then `provision_company()`, `session["company_id"]` set, redirect to hub
  - `should_redirect_to_portal()` — login goes to portal when `active_companies() != 1` OR pending invites > 0; single-company users still go straight to hub
  - `hr_app/routes/auth.py` login now routes via `should_redirect_to_portal()`; `app.py` registers `portal_bp`
- **Company provisioning** (`shared/company_setup.py`): `provision_company(company_id)` seeds COA (`ensure_fixed_coa`), 14 voucher-number prefixes (`VOUCHER_PREFIXES` constant, shared with app seed), asset categories, CompanyInfo/FiscalYearRule/AccountingPeriod/ReportSettings, InventorySettings, InvoiceTemplate defaults; restores previous company in `finally`
- **Invitation next-param**: `shared/routes/settings.py` accept/decline honor `request.form.get("next")` so portal flows return to `/portal/`
- **App shell**: "My Companies" link added to the company-switcher dropdown
- **New E2E** `tests/e2e/test_portal.py` (13 tests): login landing (multi/zero/single-company, pending invite), portal content, creation + provisioning (COA > 50, 14 voucher numbers, ≥1 period, settings, ≥4 invoice templates, session switch), quota/slug/duplicate enforcement, invite accept/decline return-to-portal, super-admin console link (asserted on `href="/superadmin/"`), landing page + superadmin login door tests
- **Tenancy bug fix** (`shared/tenancy.py`): `_collect_table_names` never recursed into `Subquery`/`Alias`/CTE nodes (they wrap a selectable via `.element`; `Subquery` is NOT a subclass of `Alias` in SQLAlchemy 2.0.51 — both derive from `AliasedReturnsRows`). Result: `Query.count()` and other aggregate/subquery queries silently bypassed tenant scoping (returned all tenants' rows). Fixed by recursing into `AliasedReturnsRows.element`.

### Verification (this session)
- Unit suite: **281 passed**
- New portal E2E in isolation: **9 passed** (at that point the file had 9 tests)
- Full E2E suite (after user's parallel edits — landing page, superadmin login door, FBR tweaks, etc.): **400 passed, 3 failed**:
  1. `test_discount_modes::TestPurchaseInvoiceParity::test_combined_by_percentage[chromium]` — Playwright navigation TimeoutError (timing flake family; passes in isolation)
  2. `test_portal.py::test_super_admin_portal_link_only_for_super_admins` — asserted `b"Super Admin Portal"` text that the template no longer contains (label is now "Super Admin Console"; test has since been updated to assert `href="/superadmin/"` instead)
  3. `test_settings_access.py::test_employee_cannot_change_fiscal_year_rule` — **real regression from the tenancy fix**: `AccountingPeriod.query.count()` in a bare `app_context()` (no active company) now correctly raises `NoActiveCompanyError`; the test needs `set_current_company(default_id)` around its count assertions (the old behavior — unfiltered count — was the bug)

### Next Move
1. Fix `test_employee_cannot_change_fiscal_year_rule`: wrap its `app_context()` blocks with `set_current_company(default_company_id)`
2. Re-run `tests/e2e/test_settings_access.py` + `tests/e2e/test_portal.py`, then full E2E
3. Commit on local main (never push): `git add -A && git commit`

### Key Files
- `shared/routes/portal.py`, `templates/portal/index.html` — user portal (new)
- `shared/company_setup.py` — `provision_company()`, `VOUCHER_PREFIXES` (new)
- `tests/e2e/test_portal.py` — portal E2E (new, 13 tests)
- `shared/tenancy.py` — `_collect_table_names` now recurses into `AliasedReturnsRows` (count-scoping fix)
- `hr_app/routes/auth.py`, `app.py`, `shared/routes/settings.py`, `templates/layouts/app_shell.html` — portal wiring
- `superadmin_app/` + `superadmin_app/templates/superadmin/login.html`, `templates/landing.html` — super admin console door + landing page (user's parallel edits, uncommitted)

## Session Summary (Jul 2026)

### Objective
Add comparative (multi-period) reporting to all finance reports (Single Period / Custom Range / Comparative toggle + dropdown+checkboxes) with side-by-side period data.

### Completed
- Period filter rewrite (`_period_filter.html`): three-mode toggle, dropdown+checkboxes panel, OK button, blue theme (`#1d4ed8`)
- Backend `_resolve_period()` returns 10-tuple: `(from_date, to_date, periods, selected_period_id, filter_mode, from_str, to_str, comp_mode, comp_periods, comp_period_ids_str)`
- **Balance Sheet**: full comparative with `_bs_data()`, `_merge_multi_period()`, merged columns, per-period totals, grand total
- **P&L**: comparative with `_pl_account_contribs()`, per-row `comp_amounts`, extra Excel/PDF columns
- **SOCIE**: comparative with per-component `comp_movements` array, comparative columns in HTML/Excel/PDF, `comp_movement_totals` in tfoot (no longer `—`)
- **Trial Balance**: comparative with `comp_dr_closing`/`comp_cr_closing` per row, comparative columns + period totals in tfoot, Excel/PDF updated
- **Cash Flow**: comparative with `comp_cf_summaries` (key totals per period), rendered as comparative summary sub-table below main statement
- **Ledger**: filter/links pass comparative params; data remains single-period (transaction-level detail)
- Removed `tr:hover td` from all CSS files; scoped hover to `tbody` only in base.html
- Fixed SOCIE `re_detail` closing column bug (each row now has proper closing value)
- Theme changed to blue `#1d4ed8`

### Key Files
- `finance_app/routes/reports.py` — all route updates (TB, BS, P&L, SOCIE, Cash Flow + `_resolve_period`)
- `finance_app/templates/accounting/_period_filter.html` — filter rewrite
- `finance_app/templates/finance/{trial_balance,balance_sheet,profit_loss,socie,cash_flow}.html` — comparative columns
- `finance_app/templates/finance/layouts/base.html` — `tbody tr:hover td` scope fix
