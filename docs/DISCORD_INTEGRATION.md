# Discord Integration Guide

This guide covers setting up and using Discord bot integration for automatic clip discovery in ClippyFront.

## Table of Contents

- [Overview](#overview)
- [Bot Setup](#bot-setup)
- [User Configuration](#user-configuration)
- [Clips Channel Guidelines](#clips-channel-guidelines)
- [Usage in Wizard](#usage-in-wizard)
- [Troubleshooting](#troubleshooting)

---

## Overview

ClippyFront can automatically discover Twitch clips shared in your Discord server by:
1. Reading messages from a designated "clips channel"
2. Extracting Twitch clip URLs from message content
3. Filtering by reaction count (community favorites)
4. Downloading clips with full metadata (creator, game, date, avatars)

**Key Features:**
- Automatic URL extraction from Discord messages
- Reaction-based filtering (minimum reactions threshold)
- Full Twitch metadata enrichment (creator name, game, timestamp)
- Creator avatar downloads
- Deduplication of clips

---

## Bot Setup

### 1. Create Discord Bot Application

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **"New Application"**
3. Give it a name (e.g., "ClippyBot")
4. Go to **Bot** section
5. Click **"Add Bot"**
6. Copy the **Bot Token** (save for `.env` configuration)

### 2. Configure Bot Permissions

The bot needs minimal permissions:

**Required Permission:**
- `Read Message History` (permission value: `65536`)

**How to enable:**
1. In Discord Developer Portal → **Bot** section
2. Under **Privileged Gateway Intents**, enable:
   - ✅ **Message Content Intent** (required to read message text)
3. Save changes

### 3. Add Bot to Your Server

Use this invite URL format:
```
https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=65536&scope=bot
```

Replace `YOUR_CLIENT_ID` with your Application ID from the Discord Developer Portal.

**Steps:**
1. Open the invite URL in a browser
2. Select your Discord server
3. Click **Authorize**
4. Complete the CAPTCHA

The bot will now appear in your server's member list.

### 4. Configure ClippyFront Environment

Add to your `.env` file:

```bash
# Discord Bot Configuration
DISCORD_BOT_TOKEN=your_bot_token_here
```

**Note:** The bot token should be kept secret and never committed to version control.

---

## User Configuration

Each user must configure their personal Discord settings in their ClippyFront profile.

### 1. Get Your Discord Channel ID

**Enable Developer Mode:**
1. Open Discord
2. Go to **User Settings** (⚙️ icon)
3. **App Settings** → **Advanced**
4. Enable **Developer Mode**

**Copy Channel ID:**
1. Right-click on the clips channel
2. Click **Copy Channel ID**
3. Save this ID for the next step

### 2. Configure Profile Settings

1. Log into ClippyFront
2. Go to **Profile/Settings** (account menu)
3. Find the **Discord Integration** section
4. Paste your **Discord Channel ID**
5. Click **Save**

**Profile Form Fields:**
- `discord_channel_id` - The channel where clips are shared (required)

**Setup Instructions in UI:**
The profile page shows:
- Channel ID input field
- Bot invite button with correct permissions
- Status indicator showing if bot is configured

---

## Clips Channel Guidelines

For best results, set up a dedicated channel following these conventions:

### Channel Purpose

**Recommended Setup:**
- Dedicated `#clips` channel for sharing Twitch clips only
- Clear channel topic/description explaining its purpose
- Pin instructions for how to share clips

**Example Channel Topic:**
```
🎬 Share your best Twitch clips here!
React with 👍 to your favorites.
Top clips get compiled automatically.
```

### Message Format

**Supported Formats:**
1. **Direct Twitch URLs in message content:**
   ```
   Check out this play! https://clips.twitch.tv/FastClipSlug-abc123
   ```

2. **Embedded links:**
   ```
   Amazing clutch: https://www.twitch.tv/streamer/clip/FastClipSlug-abc123
   ```

3. **Multiple clips in one message:**
   ```
   Today's highlights:
   https://clips.twitch.tv/FirstClip-abc
   https://clips.twitch.tv/SecondClip-def
   ```

**URL Patterns Recognized:**
- `https://clips.twitch.tv/[clip-slug]`
- `https://www.twitch.tv/[streamer]/clip/[clip-slug]`
- `https://twitch.tv/[streamer]/clip/[clip-slug]`

### Reaction System

**How It Works:**
- Users react to clips they like (any emoji)
- The wizard can filter clips by minimum reaction count
- Default: 0 reactions (includes all clips)
- Recommended: 1+ reactions (community-curated clips)

**Reaction Filtering Options in Wizard:**
- **Minimum Reactions** (0-100): Only fetch clips with this many reactions or more
- **Specific Emoji** (optional): Count only specific reaction emoji (e.g., 👍, ⭐, 🔥)

**Best Practices:**
1. Use a standard emoji for "approve this clip" (e.g., 👍)
2. Set minimum reactions to 1+ to filter out test posts
3. Higher thresholds (3-5+) for curated "best of" compilations

### Channel Moderation

**Recommended Practices:**
- Regular users can post clips
- Moderators curate by reacting to good clips
- Delete spam/off-topic messages
- Use pins for special highlight clips

**Permissions:**
- Everyone: Send Messages, Add Reactions
- Bot: Read Message History (automatically granted)
- Moderators: Manage Messages (for cleanup)

---

## Usage in Wizard

### Step 1: Project Setup

1. Create a new project in the wizard
2. Choose **Setup** → fill in project details
3. The wizard will show your configured Discord channel (if set)

### Step 2: Get Clips

**Discord Options:**

1. **Channel ID** (pre-filled from profile)
   - Shows your configured channel
   - Can override per-project if needed
   - Shows "Setup Instructions" link if not configured

2. **Message Limit** (1-100)
   - Default: 100 messages
   - How many recent messages to scan
   - Discord API maximum: 100

3. **Minimum Reactions** (0-100)
   - Default: 0 (all clips)
   - Filter clips by reaction count
   - Example: Set to 1 to only get clips people reacted to

4. **Reaction Emoji** (optional)
   - Leave empty to count all reactions
   - Specify emoji to count specific reactions only
   - Example: `👍` or `:thumbsup:`

**Fetching Process:**
1. Click **Get Clips from Discord**
2. Bot fetches recent messages from channel
3. Extracts Twitch clip URLs
4. Filters by reaction count (if configured)
5. Queues downloads with metadata enrichment

### Step 3: Automatic Metadata Enrichment

When clips are downloaded from Discord:

1. **Worker downloads video** using yt-dlp
2. **Server fetches metadata** from Twitch API:
   - Creator name (who clipped it)
   - Game name
   - Clip creation timestamp
   - Clip title
3. **Creator avatar downloaded** from Twitch
4. **Data saved** to database
5. **UI displays** full clip information

**What You See in Timeline:**
- Clip thumbnail (from video)
- Creator name ("By [username]")
- Game name
- Creation date
- Creator avatar (in overlays)

---

## Troubleshooting

### Bot Not Responding

**Check:**
1. Bot is online (green status in Discord)
2. Bot has "Read Message History" permission in channel
3. Message Content Intent is enabled in Developer Portal
4. `DISCORD_BOT_TOKEN` is correct in `.env`

**Solution:**
- Re-invite bot with correct permissions URL
- Restart ClippyFront server after `.env` changes

### No Clips Found

**Possible Causes:**
1. **No Twitch URLs in channel** - Only Twitch clip URLs are detected
2. **Reaction threshold too high** - Lower minimum reactions setting
3. **Messages too old** - Increase message limit (max 100)
4. **Channel ID incorrect** - Verify channel ID in profile

**Debug Steps:**
1. Check channel has Twitch URLs in recent messages
2. Set minimum reactions to 0
3. Increase message limit to 100
4. Verify channel ID is correct (right-click → Copy Channel ID)

### Permission Errors

**Error 403 (Forbidden):**
- Bot missing "Read Message History" permission
- Re-invite bot: https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=65536&scope=bot

**Error 404 (Not Found):**
- Channel ID is incorrect
- Bot not in server
- Channel was deleted

**Error 401 (Unauthorized):**
- Bot token is invalid or expired
- Generate new token in Developer Portal
- Update `.env` with new token

### Metadata Shows "Unknown"

If clips show "Unknown creator/game/date":

**Cause:** Twitch API enrichment failed

**Check:**
1. `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` are set in `.env`
2. Clip is still available on Twitch (not deleted)
3. Check server logs for Twitch API errors

**Solution:**
- Verify Twitch credentials in `.env`
- Check Twitch Developer Console for API quota
- Restart server after changing credentials

### Avatars Not Downloading

**Cause:** Avatar download happens after metadata enrichment

**Check:**
1. Metadata is present (creator name/ID)
2. Server logs show avatar download attempts
3. `instance/assets/avatars/` directory exists and is writable

**Logs to Look For:**
```
Attempting to download avatar for [creator] (ID: [id])
Downloaded new avatar for [creator] to [path]
```

---

## Advanced Configuration

### API Rate Limits

**Discord API Limits:**
- 100 messages per request (hard limit)
- Rate limits apply per-bot, not per-user
- Recommended: Don't fetch more than once per minute

**Twitch API Limits:**
- Metadata enrichment uses Twitch Helix API
- Rate limited by client ID (shared across all users)
- Server-side only (workers don't need credentials)

### Custom Workflow

**Example: Daily Highlight Reels**

1. Create dedicated `#daily-highlights` channel
2. Set channel topic: "React with ⭐ for daily compilation"
3. Configure wizard:
   - Message Limit: 100
   - Minimum Reactions: 3
   - Reaction Emoji: ⭐
4. Run wizard daily to auto-compile top clips

**Example: Community Clips Archive**

1. Create `#clips-archive` with all clips
2. Set minimum reactions to 0 (include everything)
3. Use higher message limit (100) to get more history
4. Tag projects by date/event for organization

---

## Security Notes

**Bot Token Security:**
- Never share bot token publicly
- Don't commit `.env` to version control
- Regenerate token if compromised
- Use environment variables in production

**Channel Privacy:**
- Bot can only read channels it has access to
- Users can only configure their own channel IDs
- Bot doesn't send messages or modify content
- Read-only access minimizes security risk

**Data Privacy:**
- Clip URLs are stored temporarily during processing
- Creator names/avatars cached for performance
- No Discord message content stored permanently
- User channel IDs stored in user profiles only

---

## Next Steps

After setting up Discord integration:

1. **Test the workflow** with a small channel
2. **Set reaction conventions** with your community
3. **Create template projects** for recurring compilations
4. **Monitor bot usage** in server audit logs
5. **Share invite link** with other users in your org

For additional help, see:
- [Features Documentation](FEATURES.md)
- [Troubleshooting Guide](TROUBLESHOOTING.md)
- [Configuration Reference](CONFIGURATION.md)
