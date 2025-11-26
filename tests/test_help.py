"""Tests for the help system."""


def test_help_index(client):
    """Test help index page loads."""
    response = client.get("/help/")
    assert response.status_code == 200
    assert b"Help Center" in response.data


def test_help_topic(client):
    """Test individual help topic loads."""
    response = client.get("/help/getting-started")
    assert response.status_code == 200
    assert b"Getting Started" in response.data


def test_help_topic_not_found(client):
    """Test 404 for non-existent help topic."""
    response = client.get("/help/non-existent-topic")
    assert response.status_code == 404


def test_help_search(client):
    """Test help search functionality."""
    response = client.get("/help/search?q=twitch")
    assert response.status_code == 200
    assert b"Search Help" in response.data


def test_help_search_with_results(client):
    """Test help search returns results."""
    response = client.get("/help/search?q=project")
    assert response.status_code == 200
    # Should find at least one result
    assert b"result" in response.data.lower()


def test_help_navigation_link(client, auth):
    """Test help link appears in navigation."""
    auth.login()
    response = client.get("/")
    assert response.status_code == 200
    assert b'href="/help/"' in response.data or b"Help Center" in response.data


def test_contextual_help_in_wizard(client, auth):
    """Test contextual help appears in project wizard."""
    auth.login()
    response = client.get("/projects/wizard")
    assert response.status_code == 200
    # Check for help popover elements
    assert b"data-bs-toggle" in response.data
    assert b"question-circle" in response.data


def test_contextual_help_in_media_library(client, auth):
    """Test contextual help appears in media library."""
    auth.login()
    response = client.get("/media")
    assert response.status_code == 200
    # Check for help elements
    assert b"question-circle" in response.data


def test_help_css_loaded(client):
    """Test help CSS file is accessible."""
    response = client.get("/static/css/help.css")
    assert response.status_code == 200
    assert b"help-icon" in response.data


def test_help_js_loaded(client):
    """Test help JavaScript file is accessible."""
    response = client.get("/static/js/help.js")
    assert response.status_code == 200
    assert b"ClippyHelp" in response.data


def test_help_markdown_rendering(client):
    """Test markdown content is rendered as HTML."""
    response = client.get("/help/getting-started")
    assert response.status_code == 200
    # Check for rendered HTML elements (h1, p, ul, etc.)
    assert b"<h2" in response.data or b"<h3" in response.data
    assert b"<ul>" in response.data or b"<ol>" in response.data


def test_help_topics_have_categories(client):
    """Test help topics are organized by category."""
    response = client.get("/help/")
    assert response.status_code == 200
    # Should have category sections
    assert b"Getting Started" in response.data or b"Projects" in response.data


def test_help_search_no_query(client):
    """Test help search with no query."""
    response = client.get("/help/search")
    assert response.status_code == 200
    assert b"search help" in response.data.lower() or b"Search Help" in response.data


def test_help_topic_has_toc(client):
    """Test help topics include table of contents."""
    response = client.get("/help/creating-projects")
    assert response.status_code == 200
    # Check that the TOC div exists (may be empty for short docs)
    assert b"col-lg-3" in response.data or b"help-toc" in response.data.lower()


def test_help_related_topics(client):
    """Test help topics show related topics."""
    response = client.get("/help/getting-started")
    assert response.status_code == 200
    # Should have related topics section or links to other topics
    assert (
        b"Related" in response.data
        or b"Next Steps" in response.data
        or b"See also" in response.data
    )
