# Timeline Rendering Specification

## Overview
This document defines the exact sequence in which video segments are assembled during the compilation process.

## Rendering Sequence

The timeline renders video segments in the following order:

```
intro -> static -> (clip -> static -> (transition -> static)) -> outro
```

### Breakdown

1. **Intro** (if selected)
   - User-selected intro video plays first

2. **Static bumper** (after intro)
   - `static.mp4` bumper plays after intro

3. **Clips with transitions** (repeating pattern)
   - For each clip in the timeline:
     - **Clip** - The actual clip content
     - **Static bumper** - Always follows each clip
     - **Transition** (if transitions are selected)
       - Custom transition video
     - **Static bumper** - Always follows transition

4. **Outro** (if selected)
   - User-selected outro video plays last

## Important Rules

### Static Bumper Usage
- Static bumpers (`static.mp4`) are **always** added between major segments
- Static appears after: intro, every clip, and every transition
- Static does NOT appear after the outro (final segment)
- Location: `instance/assets/static.mp4`

### Transition Behavior
- Transitions only appear **between clips** (not before first clip, not after last clip)
- If no custom transitions are selected (`transition_ids` is empty array):
  - Still add static bumpers between clips
  - Do not add transition videos
- If custom transitions are selected:
  - Each transition is followed by a static bumper
  - Transitions can be randomized or cycled through the list

### Edge Cases

#### No intro, no outro
```
static -> clip1 -> static -> transition -> static -> clip2 -> static
```

#### Intro only
```
intro -> static -> clip1 -> static -> transition -> static -> clip2 -> static
```

#### Outro only
```
static -> clip1 -> static -> transition -> static -> clip2 -> static -> outro
```

#### No transitions selected
```
intro -> static -> clip1 -> static -> clip2 -> static -> clip3 -> static -> outro
```

#### Single clip
```
intro -> static -> clip1 -> static -> outro
```

## Implementation

### Frontend (step-compile.js)
The compilation request must always send:
- `intro_id`: ID of selected intro (or omit if none)
- `outro_id`: ID of selected outro (or omit if none)
- `transition_ids`: Array of transition IDs (empty array `[]` if none selected)
- `clip_ids`: Array of clip IDs from timeline (required, must have at least 1)

### Backend (compile_video_v2.py)
The `_build_segments_timeline_v2()` function assembles segments in this order:

1. Add intro (if present)
2. Add static after intro
3. For each clip:
   - If not the first clip AND transitions exist: add transition + static
   - Add the clip itself
   - Add static after clip (except after last clip if outro follows)
4. Add outro (if present)

### Processing
- All segments are scaled to match output resolution
- Static bumper is processed once and reused for all insertions
- Audio sync is enforced on static bumper to prevent drift

## Example Timeline

For a project with:
- Intro: "intro.mp4"
- 3 clips: "clip1.mp4", "clip2.mp4", "clip3.mp4"
- 2 transitions: "transition1.mp4", "transition2.mp4" (cycled)
- Outro: "outro.mp4"

The final segment sequence would be:

```
1. intro.mp4
2. static.mp4
3. clip1.mp4
4. static.mp4
5. transition1.mp4    # Before clip2
6. static.mp4
7. clip2.mp4
8. static.mp4
9. transition2.mp4    # Before clip3
10. static.mp4
11. clip3.mp4
12. static.mp4
13. outro.mp4
```

Total segments: 13

## Validation

The compilation process should verify:
- At least 1 clip is present
- Intro/outro IDs (if provided) exist and belong to the user
- Transition IDs (if provided) exist and belong to the user
- Static bumper file exists at `instance/assets/static.mp4`
- All media files are accessible and valid video formats
