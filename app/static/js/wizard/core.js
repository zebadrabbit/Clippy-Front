/**
 * Wizard Core - State management, navigation, and API helpers
 */

import { initShortcuts } from './shortcuts.js';

export class WizardCore {
  constructor() {
    this.projectId = null;
    this.projectData = null;
    this.steps = ['setup', 'clips', 'arrange', 'compile'];
    this.currentStep = 1;
    this.stepModules = {}; // Lazy-loaded step modules
    this.loadState();
  }

  /**
   * Load wizard state from localStorage
   */
  loadState() {
    try {
      const params = new URLSearchParams(window.location.search);
      const urlProjectId = params.get('project_id') || params.get('projectId');

      if (urlProjectId) {
        this.projectId = parseInt(urlProjectId, 10);
        localStorage.setItem('wizard_project_id', this.projectId);
        return;
      }

      const savedProjectId = localStorage.getItem('wizard_project_id');
      if (savedProjectId) {
        this.projectId = parseInt(savedProjectId, 10);
        return;
      }

      // New project - clear old state
      localStorage.removeItem('wizard_project_id');
      this.projectId = null;
    } catch (e) {
      console.warn('[Wizard] Failed to load state:', e);
      this.projectId = null;
    }
  }

  /**
   * Save minimal state to localStorage
   */
  saveState() {
    try {
      if (this.projectId) {
        localStorage.setItem('wizard_project_id', this.projectId);
        // Update URL
        const url = new URL(window.location);
        url.searchParams.set('project_id', this.projectId);
        window.history.replaceState({}, '', url);
      } else {
        localStorage.removeItem('wizard_project_id');
      }
    } catch (e) {
      console.warn('[Wizard] Failed to save state:', e);
    }
  }

  /**
   * Navigate to a specific step
   */
  async gotoStep(step) {
    const stepNum = typeof step === 'number' ? step : parseInt(step, 10);

    if (stepNum < 1 || stepNum > 4) {
      console.error('[Wizard] Invalid step:', stepNum);
      return;
    }

    this.currentStep = stepNum;

    // Update chevron progress
    this.markChevron(stepNum);

    // Hide all steps
    document.querySelectorAll('.wizard-step').forEach(el => {
      el.classList.add('d-none');
    });

    // Show target step
    const stepEl = document.querySelector(`.wizard-step[data-step="${stepNum}"]`);
    if (stepEl) {
      stepEl.classList.remove('d-none');
    }

    // Load step module if needed
    await this.loadStepModule(stepNum);

    // Call step's onEnter hook if available
    const stepName = this.steps[stepNum - 1];
    const module = this.stepModules[stepName];
    if (module && typeof module.onEnter === 'function') {
      await module.onEnter(this);
    }
  }

  /**
   * Mark chevron as active/completed
   */
  markChevron(stepNum) {
    const chevrons = document.querySelectorAll('#wizard-chevrons li');
    const stepStr = String(stepNum);

    chevrons.forEach(li => {
      const isActive = li.dataset.step === stepStr;
      li.classList.toggle('active', isActive);

      // Mark previous steps as done
      const liStep = parseInt(li.dataset.step, 10);
      if (liStep < stepNum) {
        li.classList.add('done');
      } else if (liStep > stepNum) {
        li.classList.remove('done');
      }
    });
  }

  /**
   * Lazy-load step module
   */
  async loadStepModule(stepNum) {
    const stepName = this.steps[stepNum - 1];

    if (this.stepModules[stepName]) {
      return this.stepModules[stepName]; // Already loaded
    }

    try {
      const module = await import(`./step-${stepName}.js`);
      this.stepModules[stepName] = module;

      // Initialize module if it has an init function
      if (typeof module.init === 'function') {
        await module.init(this);
      }

      return module;
    } catch (error) {
      console.error(`[Wizard] Failed to load step module: ${stepName}`, error);
      return null;
    }
  }

  /**
   * API helper - make authenticated requests
   */
  async api(path, options = {}) {
    const defaultOptions = {
      credentials: 'include'
    };

    const mergedOptions = { ...defaultOptions, ...options };

    // Add CSRF token to headers if POST/PUT/PATCH/DELETE
    const method = (options.method || 'GET').toUpperCase();
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      if (!mergedOptions.headers) {
        mergedOptions.headers = {};
      }
      const csrfToken = this.getCSRFToken();
      if (csrfToken) {
        mergedOptions.headers['X-CSRFToken'] = csrfToken;
      }
    }

    return fetch(path, mergedOptions);
  }

  /**
   * Get CSRF token
   */
  getCSRFToken() {
    return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
  }

  /**
   * Show toast notification
   */
  showToast(message, type = 'info') {
    // TODO: Implement proper toast notifications
    console.log(`[${type.toUpperCase()}] ${message}`);
  }

  /**
   * Cleanup on navigation away
   */
  destroy() {
    // Call cleanup on loaded modules
    Object.values(this.stepModules).forEach(module => {
      if (typeof module.cleanup === 'function') {
        module.cleanup();
      }
    });
  }
}

// Initialize wizard when DOM is ready
let wizardInstance = null;

export function initWizard() {
  console.log('[Wizard] Initializing...');

  wizardInstance = new WizardCore();

  // Setup chevron click handlers
  document.querySelectorAll('#wizard-chevrons li').forEach(li => {
    li.addEventListener('click', (e) => {
      e.preventDefault();
      const targetStep = parseInt(li.dataset.step, 10);
      wizardInstance.gotoStep(targetStep);
    });
  });

  // Check for existing project from server
  if (window.wizardExistingProject) {
    wizardInstance.projectId = window.wizardExistingProject.id;
    wizardInstance.projectData = window.wizardExistingProject;
    const initialStep = window.wizardExistingProject.initialStep || 1;
    console.log('[Wizard] Loading existing project:', wizardInstance.projectId, 'at step:', initialStep);
    wizardInstance.gotoStep(initialStep);
  } else {
    wizardInstance.gotoStep(1);
  }

  // Initialize keyboard shortcuts
  initShortcuts(wizardInstance);

  return wizardInstance;
}

export function getWizard() {
  return wizardInstance;
}
