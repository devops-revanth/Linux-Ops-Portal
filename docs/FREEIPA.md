# FreeIPA / LDAP Authentication

Linux Operations Portal (LOP) can delegate authentication to a
[FreeIPA](https://www.freeipa.org/) server (or any RFC 4511-compatible LDAP
directory) while keeping **one emergency local admin** account for break-glass
access.

---

## How it works

1. User submits username + password on the login page.
2. LOP checks whether FreeIPA is enabled (`FREEIPA_ENABLED=true`).
3. **FreeIPA enabled:**
   a. Service account binds to look up the user's DN by `uid`.
   b. Re-bind with user DN + supplied password — LDAP verifies the credential.
   c. `memberOf` attribute is read to determine the portal role.
   d. A local `User` row is created or updated (role/display_name/email synced).
   e. The plain-text password is **never stored** — LDAP account rows hold the
      sentinel `!NOLOGIN` in `password_hash`.
4. **FreeIPA disabled or LDAP auth fails:** falls back to local password check.
5. Local accounts whose `auth_source="local"` always use local password auth,
   regardless of the FreeIPA toggle — this preserves the emergency admin.

---

## Role mapping

Portal roles are derived from FreeIPA group membership (`memberOf` attribute):

| FreeIPA group CN  | Portal role     | Capabilities                         |
|-------------------|-----------------|--------------------------------------|
| `LinuxAdmins`     | `administrator` | Full access including settings       |
| `LinuxOperators`  | `operator`      | Inventory read/write, patching       |
| `LinuxReadOnly`   | `readonly`      | View-only                            |
| *(no match)*      | `operator`      | Default — safe fallback              |

Role evaluation is priority-ordered: `administrator > operator > readonly`.
A user in both `LinuxAdmins` and `LinuxReadOnly` gets `administrator`.

---

## Environment variables

| Variable              | Required | Default | Description                                          |
|-----------------------|----------|---------|------------------------------------------------------|
| `FREEIPA_ENABLED`     | No       | `false` | Set to `true` to enable LDAP authentication          |
| `FREEIPA_URI`         | Yes*     | —       | LDAP URI, e.g. `ldaps://ipa.example.com`             |
| `FREEIPA_BASE_DN`     | Yes*     | —       | Search base, e.g. `dc=example,dc=com`                |
| `FREEIPA_BIND_DN`     | Yes*     | —       | Service-account DN for user lookups                  |
| `FREEIPA_BIND_PASSWORD` | Yes*  | —       | Service-account password                             |
| `FREEIPA_CA_CERT`     | No       | —       | Absolute path to PEM CA bundle for TLS verification  |
| `FREEIPA_VERIFY_CERT` | No       | `true`  | Set to `false` to skip TLS cert verification (dev)   |

\* Required when `FREEIPA_ENABLED=true`.

---

## Quick-start (FreeIPA)

```bash
# In your .env or deployment environment:
FREEIPA_ENABLED=true
FREEIPA_URI=ldaps://ipa.corp.example.com
FREEIPA_BASE_DN=dc=corp,dc=example,dc=com
FREEIPA_BIND_DN=uid=svc-lop,cn=users,cn=accounts,dc=corp,dc=example,dc=com
FREEIPA_BIND_PASSWORD=<service-account-password>
FREEIPA_CA_CERT=/etc/ipa/ca.crt        # installed by ipa-client-install
```

After setting these, use **Settings → Authentication → Test Connection** to
verify the service account can bind before deploying to production.

---

## Creating the FreeIPA service account

```bash
# On the FreeIPA server (as admin):
ipa user-add svc-lop \
    --first=LOP \
    --last=Service \
    --password          # set a strong password; use it for FREEIPA_BIND_PASSWORD

# Grant read access to user attributes (read-only; no write permissions needed)
ipa permission-add "LOP Read Users" \
    --attrs="cn,mail,memberof,uid" \
    --bindtype=permission \
    --right=read \
    --subtree="cn=users,cn=accounts,dc=corp,dc=example,dc=com"

ipa privilege-add "LOP Privilege"
ipa privilege-add-permission "LOP Privilege" --permissions="LOP Read Users"
ipa role-add "LOP Role"
ipa role-add-privilege "LOP Role" --privileges="LOP Privilege"
ipa role-add-member "LOP Role" --users=svc-lop
```

---

## FreeIPA groups required

Create the groups and add users to them:

```bash
ipa group-add LinuxAdmins    --desc="LOP administrators"
ipa group-add LinuxOperators --desc="LOP operators"
ipa group-add LinuxReadOnly  --desc="LOP read-only users"

ipa group-add-member LinuxAdmins    --users=alice
ipa group-add-member LinuxOperators --users=bob
ipa group-add-member LinuxReadOnly  --users=carol
```

---

## TLS / Certificate notes

* **`ldaps://`** (port 636) is strongly recommended for production.
* Set `FREEIPA_CA_CERT` to the IPA CA certificate.  On FreeIPA clients this
  is typically `/etc/ipa/ca.crt`.
* Setting `FREEIPA_VERIFY_CERT=false` disables certificate verification — use
  this only in isolated development environments.

---

## Emergency local access

The seeder creates one `auth_source="local"` admin account.  This account
always authenticates against the local password hash, even when FreeIPA is
enabled.  Use it if:

* The FreeIPA server is unreachable.
* You need to rotate service-account credentials.
* You need to disable FreeIPA (`FREEIPA_ENABLED=false`) temporarily.

Keep the `ADMIN_PASSWORD` environment variable set to a strong, known value
and store it in your organisation's password vault.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| "User not found in directory" | Wrong `FREEIPA_BASE_DN` | Check base DN matches your FreeIPA realm |
| "Invalid username or password" on valid creds | Service-account lookup failed silently | Test connection in Settings; check bind DN/password |
| TLS handshake errors | Wrong CA cert path or expired cert | Set `FREEIPA_CA_CERT` or temporarily use `FREEIPA_VERIFY_CERT=false` |
| Role shows as `operator` for admin | User not in `LinuxAdmins` group | `ipa group-add-member LinuxAdmins --users=<user>` |
| Connection timeout | Firewall blocking port 636 | Open port 636 from LOP host to FreeIPA server |
