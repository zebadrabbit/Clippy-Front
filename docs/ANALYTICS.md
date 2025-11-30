# Analytics System

A comprehensive analytics system for tracking clip engagement, creator activity, and game performance to help streamers optimize their content strategy.

## Features

### 📊 Overview Dashboard
- **Total Clips**: Aggregate count of all clips collected
- **Total Views**: Sum of all Twitch clip views
- **Unique Creators**: Number of distinct people creating clips
- **Games Played**: Variety of games being clipped

### 👥 Top Clip Creators
Leaderboard showing:
- Clip count per creator
- Total and average views
- Discord engagement (shares, reactions)
- Game diversity (how many different games they clip)

**Use Cases:**
- Identify active community members
- Recognize top clippers for rewards/shoutouts
- Find potential moderators or partners
- Thank contributors in streams

### 🎮 Top Games
Performance metrics by game:
- Clip count and total views
- Average view count (indicates viral potential)
- Creator diversity (community interest breadth)
- Discord engagement

**Use Cases:**
- Focus streaming schedule on high-performing games
- Identify trending content opportunities
- Understand audience preferences
- Plan content variety vs. specialization

### 📈 Engagement Timeline
Time-series data showing:
- Daily/weekly clip activity
- View trends over time
- Discord shares and reactions
- Peak activity periods

**Use Cases:**
- Optimize streaming schedule for peak clip times
- Track growth and engagement trends
- Identify seasonal or event-driven patterns
- Measure campaign/collaboration impact

### 🔥 Viral Clips
High-performing clips filtered by views:
- Clip details (title, creator, game)
- View counts and engagement metrics
- Creation timestamps
- Direct links to clips

**Use Cases:**
- Repurpose top clips for TikTok/YouTube Shorts
- Share viral moments on social media
- Highlight reels and compilations
- Cross-platform content amplification

## Data Captured

### From Twitch API
- `creator_name` - Twitch username who created the clip
- `creator_id` - Twitch user ID
- `game_name` - Game being played
- `game_id` - Twitch game/category ID
- `view_count` - Number of views on Twitch
- `created_at` - When clip was created

### From Discord
- `discord_shares` - Times clip was posted in Discord
- `discord_reactions` - Total reaction count
- `reaction_types` - Breakdown by emoji (👍, 🔥, etc.)
- `author` - Discord user who shared

## Database Models

### ClipAnalytics
Per-clip engagement tracking:
```python
clip_id, user_id, creator_name, creator_id, creator_platform,
game_name, game_id, view_count, discord_shares, discord_reactions,
discord_reaction_types, clip_created_at, first_seen_at, last_updated_at
```

### GameAnalytics
Aggregated game performance:
```python
user_id, game_name, game_id, period_type, period_start, period_end,
clip_count, total_views, avg_view_count, discord_shares,
discord_reactions, top_clip_id, top_clip_views, unique_creators
```

### CreatorAnalytics
Aggregated creator activity:
```python
user_id, creator_name, creator_id, creator_platform, period_type,
period_start, period_end, clip_count, total_views, avg_view_count,
discord_shares, discord_reactions, unique_games, top_game
```

## API Endpoints

### GET /analytics/api/overview
High-level stats summary
```json
{
  "total_clips": 1234,
  "total_views": 456789,
  "unique_creators": 89,
  "unique_games": 23,
  "date_range": {"start": "2025-01-01", "end": "2025-11-30"},
  "top_game": {"name": "Elden Ring", "clip_count": 145},
  "top_creator": {"name": "xXClipperXx", "clip_count": 67}
}
```

### GET /analytics/api/top-creators
Query params: `period` (day/week/month/all_time), `limit`
```json
{
  "period": "all_time",
  "creators": [
    {
      "creator_name": "xXClipperXx",
      "creator_id": "12345",
      "clip_count": 67,
      "total_views": 123456,
      "avg_views": 1841.7,
      "discord_shares": 12,
      "discord_reactions": 89,
      "unique_games": 8
    }
  ]
}
```

### GET /analytics/api/top-games
Query params: `period`, `limit`

### GET /analytics/api/viral-clips
Query params: `period`, `limit`, `min_views`

### GET /analytics/api/engagement-timeline
Query params: `period` (day/week/month), `days` (lookback)

### GET /analytics/api/peak-times
Hourly and daily distribution of clip creation

## Background Tasks

### aggregate_analytics_task(user_id, period)
Aggregates raw analytics into summary tables for performance.
- Runs for specific period (day/week/month/all_time)
- Can target specific user or all users
- Updates GameAnalytics and CreatorAnalytics tables

### aggregate_all_analytics_task()
Runs all period aggregations (daily cron recommended)

## Usage Examples

### In Project Wizard
When clips are fetched from Twitch:
```javascript
const clips = data.items.map(c => ({
  url: c.url,
  title: c.title,
  creator_name: c.creator_name,
  creator_id: c.creator_id,
  game_name: c.game_name,
  created_at: c.created_at,
  view_count: c.view_count || 0  // ← Analytics capture
}));
```

### In API
When clips are created:
```python
create_clip_analytics(
    clip=clip,
    user_id=current_user.id,
    view_count=obj.get("view_count", 0),
    discord_data={
        "shares": obj.get("discord_shares", 0),
        "reactions": obj.get("discord_reactions", 0),
        "reaction_types": obj.get("reaction_types", {})
    }
)
```

## Growth Opportunities

### Content Strategy
- **High-performing games**: Focus streams on games with high avg views
- **Viral potential**: Games with few clips but high avg views = untapped opportunity
- **Audience retention**: Games with consistent clip counts = loyal viewers

### Community Building
- **Top clippers**: Invite to become mods, give custom Discord roles
- **Collaboration targets**: Creators with high engagement = potential partners
- **Cross-promotion**: Share top clippers' content, build reciprocal relationships

### Cross-Platform Amplification
- **Viral clips → Shorts**: Repurpose high-view Twitch clips for TikTok/YouTube
- **Discord → Twitch**: Clips with high Discord reactions = community favorites to feature
- **Trending games**: Early viral clips = opportunity to ride trend wave

### Schedule Optimization
- **Peak clip times**: Stream during hours when most clips are created
- **Engagement patterns**: Day-of-week analysis for scheduling
- **Event correlation**: Track clip spikes around tournaments, game updates

## Implementation Details

### Database Schema

All analytics tables use the configured `TABLE_PREFIX` (e.g., `dev_`, `prod_`).

**Indexes** for query performance:
- `ClipAnalytics`: 9 indexes on user_id, clip_id, creator combinations, game, dates
- `GameAnalytics`: 4 indexes + unique constraint on (user_id, game_name, period)
- `CreatorAnalytics`: 4 indexes + unique constraint on (user_id, creator_name, period)

### Data Flow

1. **Clip Creation** → `create_clip_analytics()` captures Twitch metadata
2. **Discord Shares** → Reaction data merged on duplicate clip URLs
3. **Background Aggregation** → Daily Celery task updates summary tables
4. **Dashboard Queries** → Read from aggregated tables for performance

### Performance Optimization

**Connection Pooling**:
- Pool size: 20 (configurable via `DB_POOL_SIZE`)
- Max overflow: 30 (configurable via `DB_MAX_OVERFLOW`)
- Total: 50 concurrent database connections

**Query Optimization**:
- Aggregated tables reduce dashboard query time from seconds to milliseconds
- Indexes on frequently filtered columns (user_id, period, dates)
- Period-based partitioning for time-series queries

**Caching Strategy**:
- Redis cache for frequently accessed stats
- Period selector triggers client-side data refresh
- Aggregation tasks invalidate relevant cache keys

### Best Practices

**Data Integrity**:
- Always check `view_count` exists before storing (Twitch API sometimes omits)
- Normalize creator/game names for consistent grouping
- Handle missing Discord reaction_types gracefully (JSON field)

**Aggregation Scheduling**:
- Run `aggregate_all_analytics_task` via Celery Beat daily at low-traffic hours
- Use period-specific tasks for real-time updates during active hours
- Monitor task execution time to avoid overlapping runs

**Database Maintenance**:
- Regularly analyze query performance with `EXPLAIN ANALYZE`
- Monitor table sizes and consider archiving old data
- Vacuum tables periodically for PostgreSQL optimization

## Troubleshooting

### Missing Analytics Data

**Symptoms**: Dashboard shows zero clips despite clips existing

**Causes**:
1. Analytics capture disabled in API
2. view_count not included in Twitch response
3. Aggregation tasks not running

**Solutions**:
- Check `create_clip_analytics()` is called in `app/api/projects.py`
- Verify `view_count` in step-clips.js payload
- Manually trigger: `aggregate_analytics_task.delay(user_id, 'all_time')`

### Slow Dashboard Loading

**Symptoms**: Analytics page takes >3 seconds to load

**Causes**:
1. Database connection pool exhausted
2. Missing indexes on analytics tables
3. Large dataset without aggregation

**Solutions**:
- Increase `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` in config
- Run migration to ensure all indexes exist
- Schedule regular aggregation tasks
- Add Redis caching for frequently accessed data

### Incorrect View Counts

**Symptoms**: Total views don't match Twitch

**Causes**:
1. Clips fetched before views accumulated
2. Duplicate clip entries
3. Twitch API rate limiting

**Solutions**:
- Re-fetch clip metadata periodically to update view counts
- Implement deduplication based on clip URL
- Respect Twitch API rate limits (800 requests/minute)

## Security Considerations

- **User Isolation**: All queries filtered by `current_user.id`
- **SQL Injection**: Use SQLAlchemy ORM, never raw SQL with user input
- **Rate Limiting**: Apply to all analytics API endpoints
- **Data Privacy**: Don't expose other users' analytics

## Future Enhancements

### Near-term (v1.5-1.6)
- [ ] Chart.js integration for visual graphs
- [ ] Export analytics to CSV/PDF
- [ ] Comparison views (this month vs last month)
- [ ] Real-time dashboard updates via SSE

### Mid-term (v1.7-2.0)
- [ ] Scheduled email reports
- [ ] Correlation analysis (stream schedule → clip creation lag)
- [ ] Sentiment analysis from Discord reactions
- [ ] Auto-highlight compilation from top viral clips

### Long-term (v2.1+)
- [ ] Integration with YouTube/TikTok analytics
- [ ] Predictive trending (early viral clip detection)
- [ ] A/B testing framework (title/thumbnail impact on views)
- [ ] Machine learning for content recommendations
- [ ] Cross-platform analytics aggregation

## Related Documentation

- [Database Schema](../migrations/versions/75f559145b11_add_analytics_models.py) - Analytics table definitions
- [API Routes](ROUTES.md) - Analytics endpoint reference
- [Background Tasks](../app/tasks/aggregate_analytics.py) - Aggregation implementation
- [Configuration](CONFIGURATION.md) - Database pool settings
