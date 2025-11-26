"""
Help system routes for user documentation.

Provides wiki-style markdown documentation accessible throughout the application.
"""
from pathlib import Path

from flask import Blueprint, abort, current_app, render_template
from markdown import markdown
from markdown.extensions.fenced_code import FencedCodeExtension
from markdown.extensions.tables import TableExtension
from markdown.extensions.toc import TocExtension

help_bp = Blueprint("help", __name__)


def get_help_content_path():
    """Get the path to help content directory."""
    # Help content lives in app/help/content/
    return Path(current_app.root_path) / "help" / "content"


def get_help_file(topic):
    """
    Get help file content for a given topic.

    Args:
        topic: Help topic slug (e.g., 'getting-started', 'creating-projects')

    Returns:
        tuple: (html_content, title, toc) or (None, None, None) if not found
    """
    # Sanitize topic to prevent directory traversal
    topic = topic.replace("..", "").replace("/", "").replace("\\", "")

    help_dir = get_help_content_path()
    file_path = help_dir / f"{topic}.md"

    if not file_path.exists():
        return None, None, None

    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        # Extract title from first H1 heading if present
        title = None
        lines = content.split("\n")
        for line in lines:
            if line.startswith("# "):
                title = line[2:].strip()
                break

        # Convert markdown to HTML with extensions
        md = markdown(
            content,
            extensions=[
                TocExtension(baselevel=2, toc_depth="2-4"),
                FencedCodeExtension(),
                TableExtension(),
                "nl2br",
                "sane_lists",
            ],
        )

        # Get the generated TOC
        toc = getattr(md, "toc", "")

        return md, title or topic.replace("-", " ").title(), toc
    except Exception as e:
        current_app.logger.error(f"Error reading help file {topic}: {e}")
        return None, None, None


def get_help_index():
    """
    Get list of available help topics organized by category.

    Returns:
        dict: Categories with their topics
    """
    help_dir = get_help_content_path()

    if not help_dir.exists():
        return {}

    # Define category structure
    categories = {
        "getting-started": {
            "title": "Getting Started",
            "icon": "bi-rocket-takeoff",
            "topics": [],
        },
        "projects": {
            "title": "Projects & Compilations",
            "icon": "bi-collection-play",
            "topics": [],
        },
        "media": {
            "title": "Media Library",
            "icon": "bi-camera-video",
            "topics": [],
        },
        "integrations": {
            "title": "Integrations",
            "icon": "bi-link-45deg",
            "topics": [],
        },
        "advanced": {
            "title": "Advanced Features",
            "icon": "bi-gear",
            "topics": [],
        },
    }

    # Scan help files and categorize them
    for file_path in help_dir.glob("*.md"):
        topic_slug = file_path.stem

        # Read first few lines to get category and title
        try:
            with open(file_path, encoding="utf-8") as f:
                lines = f.readlines()

            title = None
            category = "advanced"  # default category

            for line in lines[:10]:  # Check first 10 lines
                if line.startswith("# "):
                    title = line[2:].strip()
                elif line.startswith("<!-- category: "):
                    category = line[15:].split("-->")[0].strip()

            if not title:
                title = topic_slug.replace("-", " ").title()

            if category in categories:
                categories[category]["topics"].append(
                    {"slug": topic_slug, "title": title}
                )
        except Exception:
            continue

    # Remove empty categories
    return {k: v for k, v in categories.items() if v["topics"]}


@help_bp.route("/")
def index():
    """Help home page with topic index."""
    categories = get_help_index()
    return render_template("help/index.html", categories=categories)


@help_bp.route("/<topic>")
def topic(topic):
    """Display specific help topic."""
    content, title, toc = get_help_file(topic)

    if content is None:
        abort(404)

    # Get related topics from the same category
    categories = get_help_index()
    related = []
    current_category = None

    for cat_key, cat_data in categories.items():
        for topic_item in cat_data["topics"]:
            if topic_item["slug"] == topic:
                current_category = cat_key
                related = [t for t in cat_data["topics"] if t["slug"] != topic][:3]
                break
        if current_category:
            break

    return render_template(
        "help/topic.html",
        content=content,
        title=title,
        toc=toc,
        topic_slug=topic,
        related=related,
    )


@help_bp.route("/search")
def search():
    """Search help topics (simple implementation)."""
    from flask import request

    query = request.args.get("q", "").strip().lower()

    if not query:
        return render_template("help/search.html", query="", results=[])

    help_dir = get_help_content_path()
    results = []

    if help_dir.exists():
        for file_path in help_dir.glob("*.md"):
            try:
                with open(file_path, encoding="utf-8") as f:
                    content = f.read()

                # Simple search: check if query appears in content
                if query in content.lower():
                    # Extract title
                    title = None
                    for line in content.split("\n"):
                        if line.startswith("# "):
                            title = line[2:].strip()
                            break

                    if not title:
                        title = file_path.stem.replace("-", " ").title()

                    # Get snippet around match
                    lower_content = content.lower()
                    idx = lower_content.find(query)
                    start = max(0, idx - 100)
                    end = min(len(content), idx + 100)
                    snippet = "..." + content[start:end] + "..."

                    results.append(
                        {
                            "slug": file_path.stem,
                            "title": title,
                            "snippet": snippet,
                        }
                    )
            except Exception:
                continue

    return render_template("help/search.html", query=query, results=results)
