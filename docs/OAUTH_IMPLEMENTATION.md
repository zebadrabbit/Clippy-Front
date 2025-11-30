# OAuth Implementation Guide

This document describes the OAuth2 implementation for Discord and Twitch authentication in ClippyFront.

## Overview

ClippyFront now supports OAuth2 authentication for both Discord and Twitch, enabling:
- **Secure login/signup** - Users can authenticate using their Discord or Twitch accounts
- **Account linking** - Existing users can connect their Discord/Twitch accounts to their profiles
- **Verified ownership** - OAuth ensures users actually own the accounts they claim

## Configuration

### Environment Variables

Add these to your `.env` file:

```bash
# Discord OAuth
DISCORD_CLIENT_ID=your_discord_client_id
DISCORD_CLIENT_SECRET=your_discord_client_secret
DISCORD_REDIRECT_URI=http://localhost:5000/discord/callback

# Twitch OAuth
TWITCH_CLIENT_ID=your_twitch_client_id
TWITCH_CLIENT_SECRET=your_twitch_client_secret
TWITCH_REDIRECT_URI=http://localhost:5000/twitch/callback
```

### Development vs Production

**Development (localhost):**
- Discord: `http://10.8.0.1:5000/discord/callback` or `http://localhost:5000/discord/callback`
- Twitch: `http://localhost:5000/twitch/callback` (Twitch requires localhost for HTTP)

**Production:**
- Discord: `https://dev.clipshow.io/discord/callback`
- Twitch: `https://dev.clipshow.io/twitch/callback`

### OAuth App Setup

#### Discord

1. Go to https://discord.com/developers/applications
2. Create a new application or select existing
3. Navigate to OAuth2 settings
4. Add redirect URI (e.g., `http://localhost:5000/discord/callback`)
5. Copy Client ID and Client Secret to `.env`
6. Required scopes: `identify`, `email`

#### Twitch

1. Go to https://dev.twitch.tv/console/apps
2. Create a new application or select existing
3. Add OAuth Redirect URL (e.g., `http://localhost:5000/twitch/callback`)
4. Copy Client ID and generate Client Secret, add to `.env`
5. Required scopes: `user:read:email`

**Note:** Twitch requires HTTPS for redirect URIs, but makes an exception for `http://localhost` URLs.

## Implementation Details

### Architecture

Both Discord and Twitch OAuth follow the same pattern:

1. **Login initiator** (`/login/discord`, `/login/twitch`) - Redirects to OAuth provider with `state=login`
2. **Account linking initiator** (`/connect/discord`, `/connect/twitch`) - Redirects to OAuth provider without state
3. **Unified callback** (`/discord/callback`, `/twitch/callback`) - Handles both flows based on state parameter

### State Parameter

The `state` parameter distinguishes between two flows:

- **`state=login`** - User is authenticating (login/signup flow)
  - No authentication required
  - Finds existing user or creates new account
  - Logs user in automatically

- **No state or `state != login`** - User is linking account
  - Requires authentication
  - Links OAuth account to current user
  - Validates uniqueness (prevents duplicate linking)

### Routes

#### Discord OAuth

| Route | Method | Purpose |
|-------|--------|---------|
| `/login/discord` | GET | Initiate login via Discord |
| `/connect/discord` | GET | Link Discord to existing account |
| `/discord/callback` | GET | Handle OAuth callback (both flows) |
| `/disconnect/discord` | POST | Unlink Discord from account |

#### Twitch OAuth

| Route | Method | Purpose |
|-------|--------|---------|
| `/login/twitch` | GET | Initiate login via Twitch |
| `/connect/twitch` | GET | Link Twitch to existing account |
| `/twitch/callback` | GET | Handle OAuth callback (both flows) |
| `/disconnect/twitch` | POST | Unlink Twitch from account |

### User Flow Examples

#### Login with Discord

1. User clicks "Sign in with Discord" on login page
2. Redirected to `https://discord.com/api/oauth2/authorize?...&state=login`
3. User authorizes on Discord
4. Redirected back to `/discord/callback?code=...&state=login`
5. App exchanges code for access token
6. App fetches Discord user info
7. If user exists: log them in
8. If new user: create account and log in
9. Redirect to dashboard

#### Link Discord to Existing Account

1. User navigates to Settings > Integrations
2. Clicks "Connect with Discord"
3. Redirected to `https://discord.com/api/oauth2/authorize?...` (no state)
4. User authorizes on Discord
5. Redirected back to `/discord/callback?code=...`
6. App validates user is logged in
7. App checks Discord ID isn't already linked to another account
8. Links Discord to current user
9. Redirect to Settings

### Database Schema

OAuth data is stored in the `User` model:

```python
# Discord
discord_user_id = db.Column(db.String(100), unique=True, nullable=True)
discord_channel_id = db.Column(db.String(100), nullable=True)

# Twitch
twitch_username = db.Column(db.String(100), unique=True, nullable=True)
```

**Note:** These fields are now OAuth-only. The ProfileForm no longer includes `discord_user_id` or `twitch_username` fields.

## Security Considerations

### State Parameter Validation

The state parameter should be validated to prevent CSRF attacks. Current implementation uses simple string matching (`state == "login"`). For production, consider:

- Generating random state tokens
- Storing state in session
- Validating state matches on callback

### Token Storage

Access tokens from OAuth providers are **not stored**. They're only used during the callback to fetch user info, then discarded. This limits exposure if the database is compromised.

### Uniqueness Constraints

- `discord_user_id` has a unique constraint to prevent one Discord account linking to multiple users
- `twitch_username` has a unique constraint for the same reason
- Callback handlers check for existing links before creating new ones

### Email Verification

- Discord OAuth provides verified emails (if user granted email scope)
- Twitch OAuth provides emails but verification status is unclear
- New accounts created via OAuth may have `email_verified=True` if email is provided

## UI Components

### Login Page

Two OAuth buttons appear below the traditional login form:

```html
<!-- Discord OAuth Login -->
<a href="{{ url_for('auth.login_discord') }}" class="btn btn-lg"
   style="background-color: #5865F2; color: white;">
    <i class="bi bi-discord"></i> Sign in with Discord
</a>

<!-- Twitch OAuth Login -->
<a href="{{ url_for('auth.login_twitch') }}" class="btn btn-lg"
   style="background-color: #9146FF; color: white;">
    <i class="bi bi-twitch"></i> Sign in with Twitch
</a>
```

### Settings Page (Integrations Section)

Each OAuth provider shows:
- **Connected state**: Display name/ID, disconnect button
- **Not connected state**: Connect button

Separate forms for disconnect to avoid HTML nesting issues:

```html
<!-- Discord Disconnect Form (separate to avoid nesting) -->
<form id="discord-disconnect-form" method="POST"
      action="{{ url_for('main.disconnect_discord') }}" style="display: none;">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
</form>
```

## Testing

### Local Testing

1. Set redirect URIs to `http://localhost:5000/{discord,twitch}/callback`
2. Register these URIs in Discord/Twitch developer consoles
3. Update `.env` with local redirect URIs
4. Test login flow:
   - Click "Sign in with Discord/Twitch"
   - Authorize
   - Should create account and log in
5. Test linking flow:
   - Log out, create account with traditional signup
   - Go to Settings > Integrations
   - Click "Connect with Discord/Twitch"
   - Should link account
6. Test disconnect:
   - Click disconnect button
   - Should unlink account

### Production Testing

1. Update redirect URIs to production URLs (e.g., `https://dev.clipshow.io/discord/callback`)
2. Register production URIs in Discord/Twitch developer consoles
3. Update production `.env` with HTTPS redirect URIs
4. Restart web server
5. Test all flows on production domain

## Troubleshooting

### Invalid Redirect URI

**Error:** `redirect_uri_mismatch` or similar

**Solution:**
1. Check `.env` has correct `DISCORD_REDIRECT_URI`/`TWITCH_REDIRECT_URI`
2. Verify redirect URI is registered in OAuth app settings
3. Ensure protocol matches (http vs https)
4. For Twitch on localhost, use exact string `http://localhost:5000/twitch/callback`

### Discord/Twitch Already Linked

**Error:** "Discord account already linked to another account"

**Cause:** The Discord/Twitch account is already linked to a different user

**Solution:**
1. Log in as that user and disconnect
2. Or manually update database: `UPDATE users SET discord_user_id = NULL WHERE discord_user_id = '...'`

### State Mismatch

**Error:** Callback receives wrong state or no state

**Cause:**
- User bookmarked callback URL
- OAuth provider didn't return state

**Solution:**
- Don't bookmark OAuth callback URLs
- Ensure OAuth provider is configured to return state

### Missing Scopes

**Error:** Email or username not returned from OAuth

**Cause:** User didn't grant email scope

**Solution:**
- Discord: Ensure `email` scope is requested
- Twitch: Ensure `user:read:email` scope is requested
- Ask user to reauthorize with correct scopes

## Future Enhancements

### Security
- [ ] Implement random state tokens stored in session
- [ ] Add PKCE for additional security
- [ ] Rate limit OAuth callbacks

### Features
- [ ] Allow users to set password after OAuth signup (already prompted in flash message)
- [ ] Sync avatar from Discord/Twitch
- [ ] Support additional OAuth providers (Google, Twitter, etc.)
- [ ] Two-factor authentication

### UX
- [ ] Show loading spinner during OAuth redirect
- [ ] Better error messages for OAuth failures
- [ ] Remember OAuth provider preference
- [ ] Allow unlinking if password is set

## References

- [Discord OAuth2 Documentation](https://discord.com/developers/docs/topics/oauth2)
- [Twitch Authentication Documentation](https://dev.twitch.tv/docs/authentication/)
- [Flask-Login Documentation](https://flask-login.readthedocs.io/)
