# Deployment Phases Configuration

This document outlines the 4-phase rollout strategy for the application and the environment variables needed for each phase.

## Phase 1: Whitelisted Users Only

**Goal**: Limited access to users from whitelisted domains or with whitelisted emails.

**Environment Variables**:
```bash
ALLOW_PUBLIC_SIGNUPS=false
ALLOW_ANONYMOUS_CHAT=false
DOMAINS_ALLOWLIST="example.com,trusted-org.org"
MAX_USER_SIGNUPS=-1
```

**Behavior**:
- Only users with emails from whitelisted domains can sign up
- Individual emails can be whitelisted via database (`WhitelistedUserOrm`)
- Anonymous chat is disabled - all users must authenticate
- No signup limits for whitelisted users

## Phase 2: Public Signups with Limits

**Goal**: Open to public signups but cap the total number of users.

**Environment Variables**:
```bash
ALLOW_PUBLIC_SIGNUPS=true
ALLOW_ANONYMOUS_CHAT=false
DOMAINS_ALLOWLIST=""
MAX_USER_SIGNUPS=1000
```

**Behavior**:
- Public signups allowed up to `MAX_USER_SIGNUPS` limit
- Whitelisted users still bypass the signup limit
- Anonymous chat is disabled - all users must authenticate
- Once limit is reached, only whitelisted users can sign up

## Phase 3: Fully Public with Required Login

**Goal**: Unlimited public signups, but users must authenticate to chat.

**Environment Variables**:
```bash
ALLOW_PUBLIC_SIGNUPS=true
ALLOW_ANONYMOUS_CHAT=false
DOMAINS_ALLOWLIST=""
MAX_USER_SIGNUPS=-1
```

**Behavior**:
- Unlimited public signups
- Anonymous chat is disabled - all users must authenticate
- Full access to all features for authenticated users

## Phase 4: Anonymous Access Allowed

**Goal**: Allow fully anonymous users with quota management.

**Environment Variables**:
```bash
ALLOW_PUBLIC_SIGNUPS=true
ALLOW_ANONYMOUS_CHAT=true
DOMAINS_ALLOWLIST=""
MAX_USER_SIGNUPS=-1
```

**Behavior**:
- Unlimited public signups
- Anonymous chat is enabled with quota limits
- Anonymous users tracked by IP address
- Full feature access for all users

## Related Configuration

### Quota Settings (apply to all phases):
```bash
ENABLE_QUOTA_CHECKING=true
ADMIN_USER_DAILY_QUOTA=100
REGULAR_USER_DAILY_QUOTA=25
ANONYMOUS_USER_DAILY_QUOTA=10
IP_ADDRESS_DAILY_QUOTA=50
```

### Required Settings:
```bash
DATABASE_URL=postgresql://...
NEXTJS_API_KEY=your-api-key
COOKIE_SIGNER_SECRET_KEY=your-secret-key
```

## Implementation Notes

- **Whitelisted users** always bypass signup limits in all phases
- **Anonymous users** in Phase 4 are tracked by both session ID and IP address
- **Quota checking** can be disabled by setting `ENABLE_QUOTA_CHECKING=false`
- **Domain whitelist** supports comma-separated values: `"domain1.com,domain2.org"`
- **Email whitelist** is managed via database (`WhitelistedUserOrm` table)

## Checking Current Phase

The `/api/metadata` endpoint returns configuration information:
- `is_signup_open`: Indicates if public signups are currently allowed based on limits and settings
- `allow_anonymous_chat`: Indicates if anonymous users can access the `/api/chat` endpoint