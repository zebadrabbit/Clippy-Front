---
mode: agent
---

Prompt:
In this repository, apply a style pass to improve Clippy-Front’s personality and UI tone without altering functionality.

Scope:

Only modify strings shown to users — text in flash(), render_template, return jsonify(), logging.info(), HTML button labels, and error messages.

Do not change variable names, routes, or logic.

Keep spelling American English.

Tone Guidelines:

Replace generic or systemlike phrases (e.g., “Task complete”, “Error occurred”, “Rendering...”) with Clippy-Front’s friendly, pro-creator voice: confident, slightly witty, conversational.

“Render complete.” → “Show’s in the can!”

“Rendering...” → “Splicing your highlights together...”

“Error: invalid clip format.” → “That clip didn’t vibe with the format. Let’s trim it and retry.”

Maintain clarity: humor only where meaning is still obvious.

Favor contractions and natural phrasing (“you’re”, “we’re”).

Match punctuation to energy — exclamation for success, ellipsis for processing, period for calm info.

Color and motion cues in templates:

Ensure dark-mode contrast is preserved.

Celebration & feedback:

For any “success” toast, inject a tiny celebratory note, e.g., “🎬 Showtime!” or “✨ Compilation ready.”

For any progress or waiting message, imply creative motion (rendering, mixing, cutting).

Keep all function signatures, keys, and logic untouched. Only adjust user-facing copy.

Execution Plan:

Search in /app and /frontend for user-visible strings and update them inline.

Review all UI text in .html, .js, and .py files for tone alignment.

Output a single commit titled:

chore(style): update UI copy and colors for Clippy-Front tone consistency
