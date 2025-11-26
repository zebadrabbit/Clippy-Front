/**
 * Contextual Help Component
 *
 * Provides inline help tooltips and links to full documentation.
 * Usage: Include this script and use data-help-* attributes on elements.
 */

document.addEventListener('DOMContentLoaded', function() {
    // Initialize all help tooltips
    initHelpTooltips();

    // Initialize help popovers
    initHelpPopovers();
});

/**
 * Initialize Bootstrap tooltips for help icons
 */
function initHelpTooltips() {
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    tooltipTriggerList.forEach(function(tooltipTriggerEl) {
        new bootstrap.Tooltip(tooltipTriggerEl, {
            html: true,
            trigger: 'hover focus'
        });
    });
}

/**
 * Initialize Bootstrap popovers for contextual help
 */
function initHelpPopovers() {
    const popoverTriggerList = document.querySelectorAll('[data-bs-toggle="popover"]');
    popoverTriggerList.forEach(function(popoverTriggerEl) {
        new bootstrap.Popover(popoverTriggerEl, {
            html: true,
            trigger: 'focus',
            sanitize: false
        });
    });
}

/**
 * Create a help icon element with tooltip
 * @param {string} text - Tooltip text
 * @param {string} link - Optional link to full help page
 * @returns {HTMLElement} Help icon element
 */
function createHelpIcon(text, link = null) {
    const icon = document.createElement('i');
    icon.className = 'bi bi-question-circle text-muted ms-1';
    icon.style.cursor = 'pointer';
    icon.setAttribute('data-bs-toggle', 'tooltip');
    icon.setAttribute('data-bs-placement', 'top');

    let tooltipContent = text;
    if (link) {
        tooltipContent += ` <a href="${link}" class="text-decoration-none" target="_blank">Learn more <i class="bi bi-arrow-right"></i></a>`;
    }

    icon.setAttribute('data-bs-html', 'true');
    icon.setAttribute('data-bs-title', tooltipContent);

    return icon;
}

/**
 * Create a help popover element with quick-start info
 * @param {string} title - Popover title
 * @param {string} content - Quick-start content (HTML allowed)
 * @param {string} link - Link to full documentation
 * @returns {HTMLElement} Help button element
 */
function createHelpPopover(title, content, link) {
    const btn = document.createElement('button');
    btn.className = 'btn btn-sm btn-link text-muted p-0 ms-2';
    btn.type = 'button';
    btn.setAttribute('data-bs-toggle', 'popover');
    btn.setAttribute('data-bs-placement', 'bottom');
    btn.setAttribute('data-bs-title', title);

    const popoverContent = `
        <div class="help-popover-content">
            ${content}
            <div class="mt-2 pt-2 border-top">
                <a href="${link}" class="btn btn-sm btn-outline-primary w-100">
                    <i class="bi bi-book me-1"></i> Full Documentation
                </a>
            </div>
        </div>
    `;

    btn.setAttribute('data-bs-content', popoverContent);
    btn.setAttribute('data-bs-html', 'true');
    btn.innerHTML = '<i class="bi bi-question-circle-fill"></i>';

    return btn;
}

/**
 * Add help quick-start to a form section
 * @param {string} selector - CSS selector for the element
 * @param {object} helpData - Help data {title, content, link}
 */
function addContextualHelp(selector, helpData) {
    const element = document.querySelector(selector);
    if (!element) return;

    const helpBtn = createHelpPopover(
        helpData.title,
        helpData.content,
        helpData.link
    );

    element.appendChild(helpBtn);

    // Re-initialize popover for this new element
    new bootstrap.Popover(helpBtn, {
        html: true,
        trigger: 'focus',
        sanitize: false
    });
}

// Export for global use
window.ClippyHelp = {
    createHelpIcon,
    createHelpPopover,
    addContextualHelp,
    initHelpTooltips,
    initHelpPopovers
};
