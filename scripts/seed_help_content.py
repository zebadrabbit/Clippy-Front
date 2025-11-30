#!/usr/bin/env python3
"""Seed help system with sample content."""

import os
import sys

from app import create_app
from app.models import HelpArticle, HelpCategory, HelpSection, db

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ["FLASK_ENV"] = "development"

app = create_app()


def seed_help_content():
    """Create sample help content."""
    with app.app_context():
        print("Seeding help content...")

        # Category 1: Getting Started
        cat_getting_started = HelpCategory(
            name="Getting Started",
            slug="getting-started",
            description="Learn the basics of using Clippy to create amazing video compilations",
            icon="bi-rocket-takeoff",
            sort_order=1,
            is_active=True,
        )
        db.session.add(cat_getting_started)
        db.session.flush()

        # Section: Account Setup
        section_account = HelpSection(
            category_id=cat_getting_started.id,
            name="Account Setup",
            slug="account-setup",
            description="Get your account up and running",
            sort_order=1,
        )
        db.session.add(section_account)
        db.session.flush()

        # Articles for Account Setup
        article1 = HelpArticle(
            section_id=section_account.id,
            title="Creating Your Account",
            slug="creating-your-account",
            summary="Learn how to sign up and create your Clippy account",
            content="""
<h2>Creating Your Account</h2>
<p>Getting started with Clippy is easy! Follow these steps to create your account:</p>

<h3>Step 1: Navigate to Sign Up</h3>
<ol>
    <li>Visit the Clippy homepage</li>
    <li>Click the <strong>Sign Up</strong> button in the top right corner</li>
</ol>

<h3>Step 2: Fill Out the Registration Form</h3>
<ul>
    <li><strong>Username</strong>: Choose a unique username (3-20 characters)</li>
    <li><strong>Email</strong>: Enter a valid email address</li>
    <li><strong>Password</strong>: Create a secure password (minimum 8 characters)</li>
</ul>

<h3>Step 3: Verify Your Email</h3>
<p>After registration, you'll receive a verification email. Click the link to activate your account.</p>

<blockquote>
<strong>Note:</strong> Check your spam folder if you don't see the email within a few minutes.
</blockquote>

<h3>What's Next?</h3>
<p>Once verified, you can:</p>
<ul>
    <li>Connect your Twitch and Discord accounts</li>
    <li>Upload intro/outro videos</li>
    <li>Create your first project</li>
</ul>
""",
            is_featured=True,
            is_active=True,
            sort_order=1,
        )
        db.session.add(article1)

        article2 = HelpArticle(
            section_id=section_account.id,
            title="Connecting Twitch and Discord",
            slug="connecting-integrations",
            summary="Connect your Twitch and Discord accounts to fetch clips automatically",
            content="""
<h2>Connecting Your Accounts</h2>
<p>Clippy can automatically fetch clips from your connected Twitch channel and Discord servers.</p>

<h3>Connecting Twitch</h3>
<ol>
    <li>Go to <strong>Account → Integrations</strong></li>
    <li>Enter your Twitch username in the Twitch section</li>
    <li>Click <strong>Save Changes</strong></li>
</ol>

<h3>Connecting Discord</h3>
<ol>
    <li>Go to <strong>Account → Integrations</strong></li>
    <li>Enter your Discord User ID and Channel ID</li>
    <li>Click <strong>Save Changes</strong></li>
</ol>

<h3>Finding Your Discord IDs</h3>
<p>To get your Discord IDs:</p>
<ol>
    <li>Enable Developer Mode in Discord Settings → Advanced</li>
    <li>Right-click your username and select "Copy ID"</li>
    <li>Right-click the channel and select "Copy ID"</li>
</ol>
""",
            is_featured=True,
            is_active=True,
            sort_order=2,
        )
        db.session.add(article2)

        # Section: Creating Projects
        section_projects = HelpSection(
            category_id=cat_getting_started.id,
            name="Creating Projects",
            slug="creating-projects",
            description="Learn how to create and manage video compilation projects",
            sort_order=2,
        )
        db.session.add(section_projects)
        db.session.flush()

        article3 = HelpArticle(
            section_id=section_projects.id,
            title="Your First Project",
            slug="your-first-project",
            summary="Step-by-step guide to creating your first video compilation",
            content="""
<h2>Creating Your First Project</h2>
<p>Let's walk through creating your first video compilation project!</p>

<h3>Step 1: Start a New Project</h3>
<ol>
    <li>Click <strong>New Project</strong> from your dashboard</li>
    <li>Give your project a name (e.g., "Best Moments - Week 1")</li>
    <li>Add an optional description</li>
    <li>Click <strong>Create Project</strong></li>
</ol>

<h3>Step 2: Get Clips</h3>
<p>You have several options to add clips:</p>
<ul>
    <li><strong>Fetch from Twitch</strong>: Automatically get your latest Twitch clips</li>
    <li><strong>Fetch from Discord</strong>: Import clips shared in your Discord channel</li>
    <li><strong>Manual URLs</strong>: Paste clip URLs directly</li>
</ul>

<h3>Step 3: Arrange Your Clips</h3>
<p>Once clips are downloaded, you can:</p>
<ul>
    <li>Drag and drop to reorder</li>
    <li>Add intro and outro videos</li>
    <li>Preview each clip</li>
    <li>Remove unwanted clips</li>
</ul>

<h3>Step 4: Compile</h3>
<p>When you're happy with the arrangement, click <strong>Start Compilation</strong>. Your video will be processed and ready to download!</p>
""",
            is_featured=True,
            is_active=True,
            sort_order=1,
        )
        db.session.add(article3)

        # Category 2: Features
        cat_features = HelpCategory(
            name="Features",
            slug="features",
            description="Explore Clippy's powerful features",
            icon="bi-stars",
            sort_order=2,
            is_active=True,
        )
        db.session.add(cat_features)
        db.session.flush()

        # Section: Media Library
        section_media = HelpSection(
            category_id=cat_features.id,
            name="Media Library",
            slug="media-library",
            description="Manage your intros, outros, transitions, and music",
            sort_order=1,
        )
        db.session.add(section_media)
        db.session.flush()

        article4 = HelpArticle(
            section_id=section_media.id,
            title="Uploading Intros and Outros",
            slug="uploading-intros-outros",
            summary="Add custom intro and outro videos to your library",
            content="""
<h2>Managing Your Media Library</h2>
<p>Your media library stores reusable assets like intros, outros, transitions, and background music.</p>

<h3>Uploading Media</h3>
<ol>
    <li>Navigate to <strong>Library</strong> in the main menu</li>
    <li>Click <strong>Upload Media</strong></li>
    <li>Select the media type (Intro, Outro, Transition, or Music)</li>
    <li>Choose your file</li>
    <li>Add a descriptive title</li>
    <li>Click <strong>Upload</strong></li>
</ol>

<h3>Supported Formats</h3>
<ul>
    <li><strong>Video</strong>: MP4, MOV, AVI, WebM</li>
    <li><strong>Audio</strong>: MP3, WAV, OGG, M4A</li>
</ul>

<h3>Using Media in Projects</h3>
<p>Once uploaded, your media appears in the project wizard where you can select it for any compilation.</p>
""",
            is_active=True,
            sort_order=1,
        )
        db.session.add(article4)

        # Category 3: Account & Billing
        cat_account = HelpCategory(
            name="Account & Billing",
            slug="account-billing",
            description="Manage your account settings and subscription",
            icon="bi-person-gear",
            sort_order=3,
            is_active=True,
        )
        db.session.add(cat_account)
        db.session.flush()

        # Section: Subscription
        section_subscription = HelpSection(
            category_id=cat_account.id,
            name="Subscription & Tiers",
            slug="subscription-tiers",
            description="Understand subscription tiers and billing",
            sort_order=1,
        )
        db.session.add(section_subscription)
        db.session.flush()

        article5 = HelpArticle(
            section_id=section_subscription.id,
            title="Understanding Subscription Tiers",
            slug="subscription-tiers-explained",
            summary="Learn about the different subscription tiers and their benefits",
            content="""
<h2>Subscription Tiers</h2>
<p>Clippy offers multiple tiers to fit your needs.</p>

<h3>Free Tier</h3>
<ul>
    <li>Limited storage (5 GB)</li>
    <li>720p maximum resolution</li>
    <li>30 fps maximum</li>
    <li>Watermark on videos</li>
</ul>

<h3>Pro Tier</h3>
<ul>
    <li>Increased storage (50 GB)</li>
    <li>1080p resolution</li>
    <li>60 fps</li>
    <li>No watermark</li>
    <li>Priority processing</li>
</ul>

<h3>Premium Tier</h3>
<ul>
    <li>Unlimited storage</li>
    <li>4K resolution</li>
    <li>120 fps</li>
    <li>Team collaboration</li>
    <li>API access</li>
</ul>

<p>Visit the <a href="/pricing">Pricing page</a> to compare tiers and upgrade.</p>
""",
            is_active=True,
            sort_order=1,
        )
        db.session.add(article5)

        db.session.commit()
        print("✓ Help content seeded successfully!")
        print(f"  - Created {HelpCategory.query.count()} categories")
        print(f"  - Created {HelpSection.query.count()} sections")
        print(f"  - Created {HelpArticle.query.count()} articles")


if __name__ == "__main__":
    seed_help_content()
