#!/usr/bin/env python3
"""
Test script to debug Discord emoji filtering.
Usage: python scripts/test_discord_emoji.py [channel_id]
"""
import sys

from app.integrations.discord import (
    extract_clip_urls,
    filter_by_reactions,
    get_channel_messages,
)


def main():
    channel_id = sys.argv[1] if len(sys.argv) > 1 else None

    print(f"Fetching messages from channel: {channel_id or 'default'}")
    messages = get_channel_messages(channel_id=channel_id, limit=100)
    print(f"\nTotal messages: {len(messages)}\n")

    # Show all reactions
    print("=" * 80)
    print("ALL REACTIONS FOUND:")
    print("=" * 80)
    for i, msg in enumerate(messages, 1):
        reactions = msg.get("reactions", [])
        if reactions:
            content_preview = msg.get("content", "")[:50]
            print(f"\nMessage {i}: {content_preview}")
            for r in reactions:
                emoji = r.get("emoji")
                emoji_id = r.get("emoji_id")
                count = r.get("count")
                print(f"  - emoji='{emoji}' (id={emoji_id}) count={count}")

    # Test filtering
    print("\n" + "=" * 80)
    print("FILTERING TESTS:")
    print("=" * 80)

    test_cases = [
        ("thumbsup", 1),
        (":thumbsup:", 1),
        ("+1", 1),
        ("👍", 1),
    ]

    for emoji, min_count in test_cases:
        filtered = filter_by_reactions(
            messages, min_reactions=min_count, reaction_emoji=emoji
        )
        print(f"\nFilter: emoji='{emoji}', min={min_count} -> {len(filtered)} messages")
        if filtered:
            for msg in filtered[:3]:
                print(f"  - {msg.get('content', '')[:60]}")

    # Extract clip URLs
    print("\n" + "=" * 80)
    print("CLIP URLS:")
    print("=" * 80)
    clip_urls = extract_clip_urls(messages)
    print(f"Found {len(clip_urls)} clip URLs:")
    for url in clip_urls:
        print(f"  - {url}")


if __name__ == "__main__":
    main()
