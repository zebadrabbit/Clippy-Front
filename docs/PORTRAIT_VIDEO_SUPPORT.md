# Portrait Video Support

## Overview

ClippyFront now supports portrait video compilation for platforms like YouTube Shorts, TikTok, Instagram Reels, and Instagram Stories. The system intelligently handles aspect ratio conversion when compiling landscape source clips into portrait output formats.

## Platform Presets

The following platform presets produce portrait (9:16) output:

- **YouTube Shorts**: 1080x1920, 60fps, mp4
- **TikTok**: 1080x1920, 30fps, mp4
- **Instagram Reels**: 1080x1920, 30fps, mp4
- **Instagram Stories**: 1080x1920, 30fps, mp4

## How Portrait Compilation Works

### Aspect Ratio Detection

The compilation pipeline automatically detects portrait output by comparing width and height:
```python
is_portrait_output = target_height > target_width
```

### Video Processing Pipeline

#### 1. Clips (Landscape → Portrait)

For user clips (typically 16:9 landscape):
- Scale up by 20% for a subtle zoom effect
- Crop to portrait width (1080px)
- Pad to full portrait canvas (1080x1920) with black bars top/bottom
- Centers the 16:9 content vertically

**FFmpeg Filter:**
```
scale=iw*1.2:ih*1.2,crop=1080:ih,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black
```

**Result:** Clips maintain their 16:9 aspect ratio with subtle zoom, letterboxed with black bars to fit portrait canvas.

#### 2. Static Bumpers, Transitions, Intro, Outro

For static assets (static.mp4, transitions, intros, outros):
- Scale to match portrait height (1920px)
- Crop from center to portrait width (1080px)
- Fills the entire portrait canvas

**FFmpeg Filter:**
```
scale=-1:1920,crop=1080:1920
```

**Result:** Assets fill the full portrait frame by cropping the center portion.

### Landscape/Square Output

For non-portrait outputs (landscape or square):
- Standard scaling with lanczos filter
- No letterboxing or special handling needed

**FFmpeg Filter:**
```
scale=1920:1080:flags=lanczos
```

## Implementation Details

### Code Location

Portrait handling is implemented in `app/tasks/compile_video_v2.py`:

- **Clip processing**: `_process_clip_v2()` function (lines ~318-330)
- **Asset processing**: `_process_media_file_v2()` function (lines ~489-501)

### Key Changes

1. **Resolution detection**: Parse target resolution to determine if portrait
2. **Conditional filters**: Apply different FFmpeg filters based on aspect ratio
3. **Static bumper processing**: Process static.mp4 through the same pipeline as other assets to ensure consistent resolution

### Wizard UI

The project wizard now:
- Fetches project settings from API after creation to get accurate preset values
- Derives orientation from resolution (WxH format) for display
- Shows correct preset information in compile summary (e.g., "Portrait, 30fps, mp4")

## Testing

To test portrait compilation:

1. Create a new project with "YouTube Shorts" preset
2. Add landscape clips (16:9)
3. Compile the project
4. Verify output:
   - Resolution: 1080x1920 (portrait)
   - Clips: Centered with black bars, slight zoom
   - Static bumpers: Fill entire portrait frame

## Technical Notes

### Why Letterboxing?

Rather than stretching or distorting 16:9 clips to 9:16, we preserve the original aspect ratio by:
- Adding black bars (letterboxing for portrait orientation)
- Applying a subtle 20% zoom to reduce the amount of black space
- Maintaining video quality and avoiding distortion

### Why Different Handling for Assets?

- **User clips**: Preserve aspect ratio to avoid distorting gameplay/content
- **Static assets**: Designed to be decorative, can be cropped from center to fill frame
- **Result**: Professional-looking portrait videos with proper framing

### Concatenation

All processed segments (clips + assets) output to the same resolution (e.g., 1080x1920), allowing FFmpeg to concatenate with `-c copy` for fast, lossless assembly.

## Future Enhancements

Potential improvements:
- Configurable zoom percentage (currently hardcoded to 20%)
- Smart crop detection for static assets
- Portrait-specific overlay positioning
- Custom letterbox colors
