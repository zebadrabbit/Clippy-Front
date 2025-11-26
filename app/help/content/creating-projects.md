# Creating Projects

<!-- category: projects -->

Learn how to create and manage video compilation projects in Clippy.

## The Project Wizard

The Project Wizard is your main tool for creating compilations. It guides you through a 4-step process:

1. **Setup** - Configure project settings
2. **Get Clips** - Fetch clips from sources
3. **Arrange** - Organize your timeline
4. **Compile** - Render the final video

### Step 1: Setup

#### Choose Your Source

**Twitch**: Fetch clips from your Twitch channel
- Requires your Twitch username in your profile
- Automatically fetches recent clips
- Includes clip metadata (title, views, creator)

**Discord**: Pull video links from Discord messages
- Requires Discord channel configuration
- Scans messages for video URLs
- Supports various video hosting platforms

#### Project Details

**Project Name**: Give your compilation a descriptive name
- Examples: "January Highlights", "Funny Moments 2024"
- Keep it short and memorable

**Tags**: Add comma-separated tags for organization
- Examples: gaming, highlights, funny, wins
- Makes searching easier later

**Description**: Optional notes about the project
- Remind yourself what this compilation is about
- Not visible in the final video

#### Platform Preset

Choose where you'll publish:

| Preset | Resolution | Aspect Ratio | Use Case |
|--------|-----------|--------------|----------|
| YouTube | 1920×1080 | 16:9 | Standard YouTube videos |
| YouTube Shorts | 1080×1920 | 9:16 | Vertical short-form content |
| TikTok | 1080×1920 | 9:16 | TikTok/Reels/Shorts |
| Instagram | 1080×1080 | 1:1 | Instagram feed posts |
| Twitter | 1280×720 | 16:9 | Twitter/X videos |
| Custom | Your choice | Custom | Advanced users |

#### Audio Normalization

Ensure consistent audio levels across clips:

- **Music** (-1 dB): For music-focused compilations
- **Podcast** (-3 dB): For voice-heavy content
- **Broadcast** (-2 dB): General purpose
- **Gaming** (-4 dB): Game audio with commentary

Enable by checking the box and selecting a profile.

### Step 2: Get Clips

#### Fetching from Twitch

1. The wizard automatically starts fetching your recent clips
2. Wait for the download to complete
3. Clips appear in the list with thumbnails
4. Already downloaded clips are reused (no duplicates)

#### Fetching from Discord

1. Enter date range to scan messages
2. Wizard searches for video URLs
3. Downloads each unique URL
4. Progress is shown for each download

**Tip**: The system deduplicates URLs, so the same video won't be downloaded twice.

### Step 3: Arrange

This is where you build your compilation timeline.

#### Add Intro/Outro

Intro and outro clips are special:
- **Intro** always appears first
- **Outro** always appears last
- You can select from your media library
- Optional - you can skip them

#### Add Clips

1. Browse the downloaded clips
2. Click the **+** button to add to timeline
3. Clips appear in the order you add them
4. Drag to reorder if needed

#### Transitions

Add smooth transitions between clips:
- Select a transition clip from your library
- Applied between all clips automatically
- Keep them short (2-3 seconds recommended)

#### Preview Timeline

The timeline shows:
- Order of all clips
- Duration of each segment
- Total compilation length
- Visual cards for each item

### Step 4: Compile

#### Start Compilation

Click **Start Compilation** to begin rendering:

1. Clips are processed in order
2. Transitions are inserted
3. Audio is normalized (if enabled)
4. Output is encoded to your target format

#### Monitor Progress

- Progress bar shows rendering status
- Time remaining estimate
- Current clip being processed
- Ability to cancel if needed

#### Download Result

Once complete:
- Download button appears
- Preview the final video
- Download to your computer
- Share or publish as desired

## Managing Projects

### Project Status

Projects can be in different states:

- **Draft**: Initial creation, not yet compiled
- **In Progress**: Currently being compiled
- **Completed**: Compilation finished successfully
- **Failed**: Compilation encountered an error

### Editing Projects

You can edit a project before compilation:
1. Go to **Projects** page
2. Click the project name
3. Click **Edit** to return to wizard
4. Make changes and recompile

### Deleting Projects

To remove a project:
1. Go to project details
2. Click **Delete Project**
3. Confirm deletion

**Note**: This deletes the project and compilation, but keeps media files in your library.

## Tips & Best Practices

### Keep Clips Short

- Viewers have short attention spans
- 10-30 second clips work best
- Trim longer clips before adding

### Use Intros/Outros

- Brand your content with custom intro
- Add call-to-action in outro
- Keep both under 5 seconds

### Tag Everything

- Tag projects for easy finding
- Use consistent tag names
- Include date/month tags

### Audio Matters

- Enable audio normalization
- Clips with wildly different volumes are jarring
- Test audio before finalizing

### Preview Before Downloading

- Watch the preview first
- Check for errors or issues
- Adjust and recompile if needed

## Troubleshooting

### Clips Won't Download

- Check your Twitch username is set
- Verify Discord integration is configured
- Ensure URLs are valid video links

### Compilation Fails

- Check individual clips play correctly
- Ensure clips aren't corrupted
- Try removing problematic clips

### Audio Out of Sync

- Enable audio normalization
- Check source clips aren't damaged
- Try different audio profile

---

**Related Topics:**
- [Managing Media Library](media-library)
- [Twitch Integration](twitch-integration)
- [Discord Integration](discord-integration)
