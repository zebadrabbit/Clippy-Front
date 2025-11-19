# Subscription tiers and quotas

This document describes how ClippyFront manages per-user subscription tiers, storage quotas, render-time quotas, and watermark policy.

## Overview

Tiers define limits and policy for users:

- Storage quota (bytes): total space across a user’s media library and compiled outputs
- Monthly render-time quota (seconds): how much compiled output a user can render in the current calendar month
- Watermark policy: whether to apply a watermark during processing
- Unlimited tier: bypasses all limits and disables watermarking

A per-user override can disable watermarking regardless of tier.

## Defaults and seeding

On app startup (non-testing), default tiers are ensured if none exist:

- Free: limited storage, limited render-time, watermark applied
- Pro: larger storage and render-time, watermark can be removed
- Unlimited: no limits, no watermark (intended for admin/testing)

Administrators can further customize or create new tiers in the Admin UI.

## Enforcement points

- Storage quota
  - Checked on uploads in the Media Library
  - Checked before clip downloads (and re-checked after download). If overflow occurs, the new file is removed and the request is rejected
- Render-time quota (monthly)
  - Before compiling a project, an estimate of the planned output duration is computed
  - If the remaining monthly allowance is insufficient, the compile request is blocked with details about remaining, limit, and estimated usage
  - After a successful compile, the actual output duration is recorded against the user’s monthly usage
- Watermark policy
  - Unlimited tier and per-user override disable watermarking
  - Otherwise, watermarking follows the tier’s `apply_watermark` setting

## Admin UI

- Manage tiers: Admin → Tiers
  - Create, edit, activate/deactivate, and delete tiers (deletion is guarded if assigned to users)
- Assign tiers to users: Admin → Users → Edit → Subscription Tier

## Data model and migration

- `tiers` table stores tier definitions
- Users have an optional `tier_id` foreign key
- `render_usage` table stores per-compile usage entries (seconds used, created_at)

Migrations are idempotent on PostgreSQL. If columns or indexes already exist (from manual changes or previous runs), the migration scripts will skip re-creating them to avoid aborting the transaction.

## Estimation details (pre-compile)

The planned output duration considers:

- Included clips (capped by per-clip limits when applicable)
- Selected intro/outro
- Average durations for transitions and bumpers between segments

This estimate is compared to the user’s remaining monthly allowance. The API responds with a 403 and a JSON payload when over budget, including:

- `remaining_seconds`
- `limit_seconds` (if defined)
- `estimated_seconds`

## Operational notes

- The monthly window is per calendar month (UTC)
- Storage usage sums media file sizes and compiled outputs attributed to the user’s projects
- To change tier defaults or policies, use the Admin UI or update tiers directly in the database; changes take effect immediately for future checks

## Troubleshooting

- "Out of storage" on upload or download
  - Check the user’s assigned tier and current storage usage
  - Delete or detach media to free space, increase the tier’s storage limit, or move the user to a higher tier
- "Over monthly render allowance" before compile
  - Reduce the project’s duration (fewer clips, shorter caps) or wait until the next month
  - Increase the tier’s monthly render-time limit, or assign a higher tier
- Watermark unexpectedly applied or missing
  - Verify the user’s tier, the tier’s watermark setting, and whether the user has a per-user override
