# Development Policies

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
