/**
 * Global keyboard shortcuts for the wizard
 * Handles navigation, undo/redo, save, and step-specific shortcuts
 */

export function initShortcuts(wizard) {
  console.log('[shortcuts] Initializing global keyboard shortcuts');

  document.addEventListener('keydown', (e) => {
    // Ignore shortcuts when typing in inputs
    if (e.target.matches('input, textarea, select, [contenteditable]')) {
      return;
    }

    // Navigation shortcuts
    if (e.ctrlKey && e.key === 'ArrowLeft') {
      e.preventDefault();
      const currentStep = wizard.currentStep || 1;
      if (currentStep > 1) {
        wizard.gotoStep(currentStep - 1);
      }
      return;
    }

    if (e.ctrlKey && e.key === 'ArrowRight') {
      e.preventDefault();
      const currentStep = wizard.currentStep || 1;
      if (currentStep < 4) {
        wizard.gotoStep(currentStep + 1);
      }
      return;
    }

    // Step-specific shortcuts
    const currentStep = wizard.currentStep || 1;

    // Step 1 (Setup): Ctrl+Enter to create project
    if (currentStep === 1 && e.ctrlKey && e.key === 'Enter') {
      e.preventDefault();
      const submitBtn = document.querySelector('#setup-form button[type="submit"]');
      if (submitBtn && !submitBtn.disabled) {
        submitBtn.click();
      }
      return;
    }

    // Step 2 (Clips): No special shortcuts (auto-runs)

    // Step 3 (Arrange): Undo/Redo and Save
    if (currentStep === 3) {
      // Ctrl+Z: Undo
      if (e.ctrlKey && !e.shiftKey && e.key === 'z') {
        e.preventDefault();
        if (wizard.commandHistory && wizard.commandHistory.canUndo()) {
          wizard.commandHistory.undo();
        }
        return;
      }

      // Ctrl+Y or Ctrl+Shift+Z: Redo
      if ((e.ctrlKey && e.key === 'y') || (e.ctrlKey && e.shiftKey && e.key === 'Z')) {
        e.preventDefault();
        if (wizard.commandHistory && wizard.commandHistory.canRedo()) {
          wizard.commandHistory.redo();
        }
        return;
      }

      // Ctrl+S: Save timeline
      if (e.ctrlKey && e.key === 's') {
        e.preventDefault();
        // Trigger save via step-arrange.js
        const event = new CustomEvent('wizard:save-timeline');
        document.dispatchEvent(event);
        return;
      }

      // Delete: Remove selected clip (if any)
      if (e.key === 'Delete' || e.key === 'Backspace') {
        const focused = document.activeElement;
        if (focused && focused.closest('.timeline-card')) {
          e.preventDefault();
          const removeBtn = focused.querySelector('.remove-clip');
          if (removeBtn) {
            removeBtn.click();
          }
        }
        return;
      }

      // Arrow Up/Down: Navigate clips in timeline
      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault();
        const cards = Array.from(document.querySelectorAll('.timeline-card[data-clip-id]'));
        const focused = document.activeElement;
        const currentIndex = cards.indexOf(focused);

        if (e.key === 'ArrowDown' && currentIndex < cards.length - 1) {
          cards[currentIndex + 1]?.focus();
        } else if (e.key === 'ArrowUp' && currentIndex > 0) {
          cards[currentIndex - 1]?.focus();
        } else if (currentIndex === -1 && cards.length > 0) {
          cards[0]?.focus();
        }
        return;
      }
    }

    // Step 4 (Compile): Ctrl+Enter to start compilation
    if (currentStep === 4 && e.ctrlKey && e.key === 'Enter') {
      e.preventDefault();
      const startBtn = document.getElementById('start-compile');
      if (startBtn && !startBtn.disabled) {
        startBtn.click();
      }
      return;
    }

    // Global: Escape to close modals or cancel operations
    if (e.key === 'Escape') {
      // Let modals handle their own escape
      return;
    }

    // Global: ? to show keyboard shortcuts help (future enhancement)
    if (e.key === '?' && !e.ctrlKey && !e.shiftKey && !e.altKey) {
      e.preventDefault();
      showShortcutsHelp(wizard);
      return;
    }
  });

  console.log('[shortcuts] Global keyboard shortcuts initialized');
}

/**
 * Show keyboard shortcuts help modal (future enhancement)
 */
function showShortcutsHelp(wizard) {
  const currentStep = wizard.currentStep || 1;

  const shortcuts = {
    global: [
      { keys: 'Ctrl + ←/→', desc: 'Navigate between steps' },
      { keys: '?', desc: 'Show this help' }
    ],
    1: [
      { keys: 'Ctrl + Enter', desc: 'Create project' }
    ],
    2: [],
    3: [
      { keys: 'Ctrl + Z', desc: 'Undo' },
      { keys: 'Ctrl + Y', desc: 'Redo' },
      { keys: 'Ctrl + S', desc: 'Save timeline' },
      { keys: '↑/↓', desc: 'Navigate clips in timeline' },
      { keys: 'Delete', desc: 'Remove selected clip' }
    ],
    4: [
      { keys: 'Ctrl + Enter', desc: 'Start compilation' }
    ]
  };

  const stepShortcuts = shortcuts[currentStep] || [];
  const allShortcuts = [...shortcuts.global, ...stepShortcuts];

  if (!allShortcuts.length) {
    console.log('[shortcuts] No shortcuts to show');
    return;
  }

  // Create a simple alert for now
  const helpText = allShortcuts
    .map(s => `${s.keys}: ${s.desc}`)
    .join('\n');

  alert(`Keyboard Shortcuts:\n\n${helpText}`);
}
