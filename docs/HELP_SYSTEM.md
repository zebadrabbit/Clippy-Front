# Help System - Implementation Guide

## Overview

The ClippyFront help system provides wiki-style markdown documentation accessible throughout the application with contextual help tooltips and popovers.

## Components

### 1. Help Blueprint (`app/help/`)
- **routes.py**: Flask blueprint with markdown rendering
- **content/**: Markdown files organized by topic
- **Templates**: Help index, topic view, and search

### 2. Static Assets
- **js/help.js**: Contextual help JavaScript utilities
- **css/help.css**: Help-specific styling

### 3. Help Content
Located in `app/help/content/`:
- `getting-started.md` - Introduction and quick start
- `creating-projects.md` - Project wizard walkthrough
- `media-library.md` - Media management guide
- `twitch-integration.md` - Twitch setup and usage
- `discord-integration.md` - Discord setup and usage
- `tiers-quotas.md` - Subscription tier information
- `faq.md` - Frequently asked questions

## Creating New Help Topics

### 1. Create Markdown File

Create a new `.md` file in `app/help/content/`:

```markdown
# Your Topic Title

<!-- category: getting-started -->

Your content here in markdown format.

## Section Heading

Content with **bold**, *italic*, `code`, and [links](url).

### Subsection

- Bullet points
- Are supported

| Tables | Work |
|--------|------|
| Cell 1 | Cell 2 |

```bash
# Code blocks with syntax highlighting
command --flag value
```
```

### 2. Set Category

Add a category comment at the top:
```markdown
<!-- category: getting-started -->
<!-- category: projects -->
<!-- category: media -->
<!-- category: integrations -->
<!-- category: advanced -->
```

### 3. Link from Other Topics

Reference your new topic:
```markdown
See [Your Topic](your-topic-slug) for more details.
```

## Adding Contextual Help

### 1. Tooltip (Simple)

For brief explanations:

```html
<label class="form-label d-flex align-items-center">
  Field Name
  <i class="bi bi-question-circle text-muted ms-1 help-icon"
     data-bs-toggle="tooltip"
     data-bs-placement="top"
     data-bs-html="true"
     title="Brief explanation of this field"></i>
</label>
```

### 2. Popover (Detailed)

For quick-start guides with links:

```html
<h2 class="mb-0 d-flex align-items-center">
  Page Title
  <button type="button" class="btn btn-sm btn-link text-muted p-0 ms-2"
          data-bs-toggle="popover"
          data-bs-placement="bottom"
          data-bs-title="Quick Start: Feature Name"
          data-bs-html="true"
          data-bs-content='<p class="mb-2">Brief description:</p>
                           <ul class="small mb-2">
                             <li>Point 1</li>
                             <li>Point 2</li>
                           </ul>
                           <div class="mt-2 pt-2 border-top">
                             <a href="{{ url_for("help.topic", topic="topic-slug") }}" class="btn btn-sm btn-outline-primary w-100">
                               <i class="bi bi-book me-1"></i> Full Guide
                             </a>
                           </div>'>
    <i class="bi bi-question-circle-fill"></i>
  </button>
</h2>
```

### 3. Direct Link

For simple help links:

```html
<a href="{{ url_for('help.topic', topic='topic-slug') }}" class="btn btn-sm btn-link text-muted">
  <i class="bi bi-question-circle"></i>
</a>
```

## JavaScript API

The help.js provides a JavaScript API:

```javascript
// Create a tooltip icon
const icon = window.ClippyHelp.createHelpIcon('Tooltip text', '/help/topic');

// Create a popover
const popover = window.ClippyHelp.createHelpPopover(
  'Quick Start Title',
  '<p>Content here</p>',
  '/help/full-guide'
);

// Add contextual help to an element
window.ClippyHelp.addContextualHelp('#my-element', {
  title: 'Quick Start',
  content: '<p>Help content</p>',
  link: '/help/topic'
});

// Re-initialize tooltips/popovers after dynamic content
window.ClippyHelp.initHelpTooltips();
window.ClippyHelp.initHelpPopovers();
```

## Access Points

Users can access help from:

1. **Navigation Bar**: Question mark icon (top right)
2. **Contextual Help**: Question mark icons throughout the UI
3. **Direct URL**: `/help` for index, `/help/<topic>` for specific topics
4. **Search**: `/help/search?q=query`

## Best Practices

### Writing Help Content

1. **Be concise**: Users want quick answers
2. **Use examples**: Show, don't just tell
3. **Add screenshots**: Visual aids are helpful (when available)
4. **Link between topics**: Create a web of related content
5. **Update regularly**: Keep content current with features

### Contextual Help

1. **Use tooltips for definitions**: Brief explanations only
2. **Use popovers for quick-starts**: Step-by-step guidance
3. **Link to full docs**: Always provide "Learn more" links
4. **Don't overwhelm**: Help icons on key fields only
5. **Test on mobile**: Ensure popovers work on small screens

### Help Content Organization

1. **Getting Started**: Basics for new users
2. **Projects**: Project and compilation workflows
3. **Media**: Media library management
4. **Integrations**: External service setup
5. **Advanced**: Tiers, teams, automation

## Maintenance

### Adding a New Feature

When adding a feature:
1. Create or update relevant help topic
2. Add contextual help in the UI
3. Update related topics with cross-links
4. Test help content for accuracy

### Updating Existing Content

1. Edit the markdown file in `app/help/content/`
2. Changes appear immediately (no restart needed)
3. Update related topics if necessary
4. Verify links still work

### Removing Deprecated Features

1. Update or remove the help topic
2. Remove contextual help from templates
3. Update links in other topics
4. Consider adding a redirect or note

## Troubleshooting

### Help page shows 404
- Verify markdown file exists in `app/help/content/`
- Check filename matches URL slug (dashes, not underscores)
- Ensure file has `.md` extension

### Tooltip/popover not showing
- Check Bootstrap is loaded before help.js
- Verify `data-bs-toggle` attribute is correct
- Run `ClippyHelp.initHelpTooltips()` or `initHelpPopovers()` if content is dynamic

### Markdown not rendering
- Verify Markdown library is installed (`pip install Markdown==3.5.1`)
- Check file encoding is UTF-8
- Ensure no syntax errors in markdown

### Search not finding content
- Search is case-insensitive and searches full content
- Try broader keywords
- Check that markdown files are in the correct directory

## Future Enhancements

Potential improvements:
- Full-text search with ranking
- Video tutorials embedded in help
- User feedback ("Was this helpful?")
- Admin interface for editing help
- Versioned help content
- Multi-language support
- Analytics on help usage
