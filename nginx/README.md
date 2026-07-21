# Nginx Configuration

This directory contains the Nginx reverse proxy configuration for the Linux Operations Portal.

## Files

| File | Purpose |
|------|---------|
| `nginx.conf` | Production Nginx server block (HTTP → HTTPS redirect + TLS proxy) |

## Deployment

1. Copy `nginx.conf` to `/etc/nginx/sites-available/lop`
2. Replace `your-domain.example.com` with your real FQDN
3. Symlink into sites-enabled:
   ```bash
   ln -s /etc/nginx/sites-available/lop /etc/nginx/sites-enabled/lop
   nginx -t && systemctl reload nginx
   ```
4. Obtain a TLS certificate:
   ```bash
   sudo certbot --nginx -d your-domain.example.com
   ```

## Docker usage

When deploying with `docker-compose.yml`, Nginx runs as a sidecar container.
Uncomment the `nginx` service block in `docker-compose.yml` (not yet added) and
mount `nginx.conf` into `/etc/nginx/conf.d/lop.conf`.

## Environment variable

Set `APP_BASE_URL` to match the FQDN so the Settings page shows the correct API endpoint URL:

```bash
APP_BASE_URL=https://your-domain.example.com
```
