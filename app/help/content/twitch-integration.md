# Twitch Integration

<!-- category: integrations -->

Connect your Twitch account to automatically fetch clips for your compilations.

## Setting Up Twitch

### Add Your Username

1. Go to **Profile** (click your user menu)
2. Find the **Twitch Integration** section
3. Enter your **Twitch username** (without @)
4. Click **Save Changes**

That's it! No OAuth or tokens needed - just your username.

## How It Works

When you create a project using the **Twitch route**:

1. Clippy fetches your recent clips from Twitch
2. Clips are downloaded to your media library
3. Metadata is preserved (creator, game, views, etc.)
4. Duplicate clips are automatically detected and reused

## Fetching Clips

### Automatic Fetching

In the Project Wizard:

1. Choose **Twitch** as your route
2. Click **Next** to proceed to "Get Clips"
3. Wizard automatically starts fetching
4. Wait for clips to download

### What Gets Fetched

Default behavior:
- Recent clips from your channel
- Up to 100 most recent clips
- Sorted by creation date

Clip metadata includes:
- **Title**: Clip name from Twitch
- **Creator**: Who created the clip
- **Game**: What game was being played
- **View Count**: How many views
- **Created Date**: When clip was created
- **Thumbnail**: Preview image

## Using Fetched Clips

Once downloaded:

1. Clips appear in the "Get Clips" step
2. Each clip shows thumbnail and metadata
3. Click **+** to add to your timeline
4. Arrange order in the "Arrange" step
5. Compile when ready

## Clip Deduplication

Clippy is smart about duplicates:

- Checks URL before downloading
- Reuses existing files in your library
- Saves time and storage space
- Works across multiple projects

## Troubleshooting

### No Clips Appear

**Check username:**
- Verify Twitch username is correct
- It should match your channel exactly
- Case doesn't matter

**Check clip availability:**
- You must have clips created on your channel
- Only published, non-deleted clips are fetched
- Clips must be publicly accessible

### Clips Won't Download

**Network issues:**
- Check your internet connection
- Twitch servers may be slow
- Try again later

**Rate limiting:**
- Twitch limits requests
- Wait a few minutes and retry
- Contact admin if issue persists

### Missing Metadata

Some clips may have incomplete info:
- Creator deleted their account
- Game information changed
- Clip was edited on Twitch

This doesn't affect the video itself.

### Old Clips Not Showing

Twitch API limits:
- Only recent clips are available
- Typically last 3-6 months
- Older clips may not appear
- Download important clips early

## Privacy & Permissions

### What Clippy Accesses

- **Public clips only**: Only publicly viewable clips
- **No account access**: Doesn't log into your Twitch
- **Read-only**: Can't modify or delete Twitch clips
- **Your library only**: Can't see other users' clips

### What Clippy Doesn't Access

- Your Twitch password
- Private videos
- Stream keys
- Chat logs
- Follower lists
- Subscription data

## Best Practices

### Regular Downloads

- Download clips regularly
- Don't wait until you need them
- Older clips may become unavailable
- Build your library over time

### Tag Clips

After downloading:
- Add descriptive tags
- Makes finding clips easier later
- Examples: "funny", "rage", "win", "fail"

### Review Before Adding

- Watch clips before adding to project
- Some clips may be low quality
- Check audio levels
- Remove boring parts

### Organize by Game

Use tags for game names:
- "valorant", "apex", "minecraft"
- Find game-specific compilations easily
- Create themed videos

## Advanced Tips

### Seasonal Compilations

Create monthly or yearly compilations:
1. Download clips throughout the period
2. Tag with month/year
3. Filter by tag when creating project
4. Compile your best moments

### Clip Collections

Organize by type:
- "best-plays" for highlights
- "funny-moments" for comedy
- "rage-clips" for reactions
- Mix and match for variety

### Viewer Engagement

Use clip metadata:
- Show creator names in overlays
- Thank clip creators in outro
- Highlight most-viewed clips
- Credit in video description

---

**Related Topics:**
- [Creating Projects](creating-projects)
- [Managing Media Library](media-library)
- [Discord Integration](discord-integration)
