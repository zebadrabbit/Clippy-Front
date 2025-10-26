---
mode: agent
---
Goal:
Update all user-visible text in this repository so that Clippy-Front speaks in the Clip Lab voice — relaxed, maker-oriented, Twitch-native, and consistent with the clip → compilation workflow.

Keep logic intact. Only adjust text shown to users in UI components, templates, notifications, logging, and API responses.

🧭 Style Directives

Core metaphor: “Clip Lab” — a creative workbench for Twitch clips, not a film studio.

Main flow: clip → format (preset) → compilation.

Avoid broadcast or Hollywood terms: studio, scene, director, episode, act, premiere.

Prefer maker / streamer terms: build, mix, drop, craft, queue, batch, clip, compilation, preset, format.

Maintain lowercase casual tone unless branding requires caps.

Use concise, punchy phrasing like chat messages.

Contractions welcome (“you’re”, “we’re”).

Keep humor light, competent, self-aware.

One emoji max per sentence, only when it adds tone (🎬, ⚙️, 🔥, 💾, 🎉).

Keep “clip” terminology literal — never replace with “scene.”

💬 Replacement Examples
Old phrasing	New Clip Lab phrasing
“Render complete.”	“Clips stitched — compilation ready 🎉”
“Rendering…”	“Mixing your clips…”
“Error: invalid clip format.”	“That clip didn’t vibe with the preset. Try trimming it.”
“Start render”	“Start mixdown”
“Task progress”	“Render queue”
“Add to project”	“Add to compilation”
“Template”	“Preset format”
“Export complete”	“Drop saved 💾”

🪛 Implementation Instructions

Search the workspace for user-facing strings in .py, .html, .js, .vue, or .jsx files.

Update copy inline following the style directives.

Do not modify variable names, keys, routes, or logic.

Preserve punctuation, capitalization, and escape sequences where required by code.

If uncertain, leave a comment # TODO: tone-check rather than guessing.

Commit under:

chore(style): adopt Clip Lab tone and terminology for UI copy
