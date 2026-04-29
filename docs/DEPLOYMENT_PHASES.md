# Deployment Configuration

The API now runs in authenticated-user-only mode. Whitelist-based signup gates and anonymous chat paths have been removed.

## Required Behavior

- All `/api/chat` and `/api/quota` requests must be authenticated.
- User creation happens on first successful authenticated `/api/auth/me`.
- No domain/email whitelist or public-signup-limit controls are applied.

## Related Configuration

### Quota Settings
```bash
ENABLE_QUOTA_CHECKING=true
ADMIN_USER_DAILY_QUOTA=100
REGULAR_USER_DAILY_QUOTA=25
PRO_USER_DAILY_QUOTA=50
MACHINE_USER_DAILY_QUOTA=99999
```

### Required Settings
```bash
DATABASE_URL=postgresql://...
COOKIE_SIGNER_SECRET_KEY=your-secret-key
```
