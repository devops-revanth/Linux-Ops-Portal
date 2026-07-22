# LOP Plugins Directory

This directory is reserved for future LOP integrations and plugins.

## Planned integrations

| Plugin | Description | Status |
|--------|-------------|--------|
| `vmware/` | VMware vSphere inventory sync | Planned |
| `ansible/` | Ansible playbook execution | Planned |
| `ldap/` | Extended LDAP/FreeIPA features | Planned |
| `azure/` | Azure AD and Azure VM inventory | Planned |
| `smtp/` | Email notifications and alerting | Planned |

## Plugin structure (future)

Each plugin will follow this layout:

```
plugins/<name>/
  __init__.py       # Plugin entry point
  config.py         # Plugin-specific configuration keys
  models.py         # Additional database models (optional)
  routes.py         # Flask blueprint routes (optional)
  README.md         # Plugin documentation
```

Plugins will be auto-discovered by the application at startup when
`PLUGIN_<NAME>_ENABLED=true` is set in `/etc/lop/lop.env`.

Nothing is implemented here yet. This directory exists to keep the
architecture future-proof.
