# Discord Integration

<!-- category: integrations -->

Connect your Discord to fetch video clips shared in your channels.

## Setting Up Discord

### Configure Channel Access

1. Go to **Profile** (click your user menu)
2. Find **Discord Integration** section
3. Your admin must provide:
   - Bot token (configured server-side)
   - Channel ID you want to scan

4. Enter the **Channel ID** in your profile
5. Click **Save Changes**

### Getting Your Channel ID

In Discord:

1. Enable **Developer Mode**:
   - User Settings → Advanced → Developer Mode
2. Right-click the channel
3. Click **Copy ID**
4. Paste this ID into your Clippy profile

## How It Works

When creating a project with **Discord route**:

1. Specify a date range to scan
2. Clippy reads messages from your channel
3. Extracts video URLs from messages
4. Downloads each unique video
5. Adds to your media library

## Fetching Clips from Discord

### In the Project Wizard

1. Choose **Discord** as your route
2. Click **Next** to "Get Clips" step
3. Enter **Start Date** and **End Date**
4. Click **Fetch Clips**
5. Wait for scanning and downloads to complete

### What Gets Scanned

The integration looks for:
- Direct video attachments
- YouTube links
- Twitch clip links
- Discord CDN video links
- Other common video URLs

### Deduplication

Smart URL handling:
- Same URL won't be downloaded twice
- Checks against your existing library
- Saves bandwidth and storage
- Works across multiple projects

## Supported Platforms

Discord integration can download from:

- **Direct uploads**: Videos attached to Discord messages
- **YouTube**: Standard videos and Shorts
- **Twitch**: Clip links
- **Streamable**: Uploaded videos
- **Other platforms**: Most direct video URLs

## Privacy & Permissions

### What Bot Can Access

- **Messages**: Text content in configured channel
- **Attachments**: Files attached to messages
- **Links**: URLs shared in messages

### What Bot Cannot Access

- Private DMs
- Other servers
- Channels not configured
- User data beyond messages

### Your Data

- Downloaded videos are private to you
- Other users can't see your Discord clips
- Videos stored in your personal library
- Delete anytime from Media Library

## Troubleshooting

### Channel ID Not Working

**Check channel access:**
- Verify bot is in the server
- Channel must be accessible to bot
- Check permissions allow reading

**Check ID format:**
- Should be numbers only
- Example: `123456789012345678`
- Copy directly from Discord

### No Clips Found

**Check date range:**
- Ensure messages exist in that timeframe
- Videos must be shared, not just text
- Try wider date range

**Check message content:**
- Bot only finds video links
- Text-only messages are skipped
- Ensure URLs are valid

### Downloads Failing

**URL issues:**
- Some platforms block automated downloads
- Links may have expired
- Private videos won't download

**Network issues:**
- Check internet connection
- Some hosts rate-limit downloads
- Try again later

### Slow Scanning

**Large date ranges:**
- Scanning many messages takes time
- Narrow date range for faster results
- Consider scanning month by month

**Busy server:**
- High traffic may slow processing
- Peak hours may be slower
- Try during off-peak times

## Best Practices

### Organize by Date

Use tags with dates:
- "2024-january"
- "december-clips"
- Makes finding clips easier

### Regular Scans

- Scan Discord weekly or monthly
- Don't let clips pile up
- Easier to manage smaller batches

### Clean Up Links

Before scanning:
- Ask community to share clips in specific channel
- Organize clip-sharing sessions
- Makes finding good content easier

### Tag After Download

Add descriptive tags:
- Who shared the clip
- What game/content
- Type of moment (funny, epic, etc.)

## Advanced Usage

### Dedicated Clip Channels

Create a Discord channel just for clips:
- #clips or #highlights
- Community shares best moments
- Easy to scan and download
- Builds engagement

### Weekly Compilations

1. Scan previous week
2. Download all clips
3. Review and select best
4. Create compilation
5. Share back to Discord

### Community Involvement

- Ask community to share clips
- Credit clip sharers in video
- Create themed compilation requests
- Build audience participation

### Multiple Channels

If you manage multiple servers:
- Configure different channel IDs
- Create projects for each community
- Separate libraries by server
- Cross-promote compilations

---

**Related Topics:**
- [Creating Projects](creating-projects)
- [Managing Media Library](media-library)
- [Twitch Integration](twitch-integration)
