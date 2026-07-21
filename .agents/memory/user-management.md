---
name: User Management module
description: Dedicated /users blueprint for user list, role editing, enable/disable, password reset, delete.
---

## Rule
User management lives at `/users` (blueprint name "users") — NOT in Settings.
Settings page contains: Locations, Environments, Owners, Directory Services, API/Ansible Integration.

## Blueprint
`app/blueprints/users/` — queries.py (all DB logic), routes.py (thin controllers).
Template: `app/templates/users/index.html` — paginated table with modals for all actions.

## Key constraints
- LDAP users (auth_source="ldap"): password reset disabled; role and status are editable.
- Local users: all actions available.
- Cannot deactivate your own account (enforced in toggle_user_active).
- Cannot delete the last user or yourself (enforced in delete_user).
- Cannot deactivate the last active user.

## Routes
POST /users/add, /users/<id>/change-password, /users/<id>/edit-role, /users/<id>/toggle-active, /users/<id>/delete

**Why:** Separating users from settings keeps settings focused on config; users is a first-class operational module.
