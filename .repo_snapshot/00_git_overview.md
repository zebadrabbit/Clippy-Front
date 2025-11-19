# Repo Metadata
Repo: ClippyFront
Default branch:
HEAD: b765a95
HEAD date: 2025-11-01 04:25:32 +0000

## Recent commits (last 30)
b765a95 chore(release): 0.10.0
1738f95 feat(project-details): show only used clips after successful compile and display count (X used of Y)
a32c562 chore(release): 0.9.0 – timeline-aware compile, worker app caching, syntax fix, and docs
62f9b2d chore(release): v0.8.5 — finalize canonical /instance paths, GPU worker + docs alignment, run script hardening
af07b5e docs: document ALLOW_EXTERNAL_URLS flag and clip sources policy in README
aa47dfd feat: add ALLOW_EXTERNAL_URLS (default false) and enforce Twitch/Discord-only URLs when disabled
a70c0b6 chore: harden legacy 'once' schedules as read-only
b5abe00 feat: operational console (Blessed TUI) and logging noise reductions
d250089 feat: overlays + scheduling cleanup; docs and version bump to 0.8.2\n\n- Fix avatar overlay resolution on GPU workers via AVATARS_PATH normalization; add OVERLAY_DEBUG and startup sanity warning (once per process).\n- Reduce noisy startup logs (DB URI, runtime schema updates) to once per process.\n- Remove legacy 'once' schedule creation from UI/API; add monthly UI in modals; keep backward compat read.\n- Update README and workers docs; add CHANGELOG entry; bump version to 0.8.2.
69bac6c fix(overlay): resolve avatars when AVATARS_PATH points to assets or avatars; add detailed debug to trace matches
0d9573d merge: feat/tiers-and-quotas-admin into main (v0.8.1)
94b08b2 chore: bump version to 0.8.1; docs: refresh README and guides; feat: improve NVENC probe and checker; chore: lint import order; docs: add avatar cache maintenance script
3114096 docs: clarify container CLIPPY_INSTANCE_PATH and fix MEDIA_PATH_ALIAS example to /mnt/clippy/
3c86047 docs(worker): use CLIPPY_INSTANCE_PATH=/app/instance inside containers; keep host mount at /mnt/clippy\n\n- Update docs/gpu-worker.md and docs/workers.md to prevent path mismatches\n- Clarify host vs container paths and REQUIRED mount enforcement
2def6b4 fix(api,worker): avoid re-downloading identical clips by slug/normalized URL; set CLIPPY_INSTANCE_PATH=/app/instance in GPU worker container to fix missing file paths\n\n- API: dedupe by Twitch slug or normalized URL across user projects; skip re-downloads\n- Worker: pass CLIPPY_INSTANCE_PATH as /app/instance (container path), keeping host mount at /mnt/clippy\n- This resolves errors like '/mnt/clippy/...: No such file or directory' inside the container
70d1ab8 style: black formatting after mount enforcement change
ff213ac fix(download): avoid yt-dlp invalid rate-limit by passing --max-filesize in bytes and stripping --limit-rate from custom args
4ba9368 docs: add subscription tiers & quotas guide; update README with tiers, admin UI, and upgrade instructions; note idempotent migrations
5dc793b migrations: format Alembic script via black
0a3909b feat: subscription tiers, quota enforcement, and admin UI
cf310f7 merge: docs/copilot-rules into main (0.7.2 theme + wizard + docs)
b716463 feat(theme): add 'Compilation' media type color and admin field; feat(wizard): make Downloaded Clips collapsible with auto-collapse/expand; docs: clarify venv usage; chore: bump to 0.7.2; db: add migration for media_color_compilation
2d98de6 docs: consolidate worker guides for Linux/WSL2 + clarify flags; bump to 0.7.1
54ca5de feat: themeable media type colors; color-coded Media Library and timeline; DnD insert marker; extract inline scripts; bump to 0.7.0
b87d419 build(release): bump version to 0.6.0 and refresh docs (themes, navbar, media upload); fix theme delete redirect; update CHANGELOG
311ed4b fix(db): add runtime DDL to create users.password_changed_at if missing to avoid PG errors after model change
366b2bb feat(auth): track password_changed_at and show accurate 'Last changed' in Account Settings; remove Security/Notifications from sidebar
9d6dd16 fix(auth): add POST /auth/change-password and wire Account Settings modal to endpoint; include CSRF\n\nPrevents 405 on password change and validates current/new/confirm.
c1601f5 feat(admin): add System Configuration page with editable settings and restart controls\n\n- Introduce SystemSetting model and runtime overrides\n- New admin routes: /admin/config and /admin/restart/<target>\n- UI: system_config.html with grouped settings and restart buttons\n- Link from Admin Dashboard\n- Lint/format/tests passing
a765491 fix(admin): use MediaType enum for storage stats filter to satisfy PostgreSQL enum comparisons

## Top contributors
    63	zebadrabbit
