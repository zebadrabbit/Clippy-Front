/**
 * Wizard Core - State management, navigation, and API helpers
 */

export class WizardCore {
  constructor() {
    this.projectId = null;
    this.projectData = null;
    this.wizardState = {}; // Persisted wizard state from database
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

    // Call previous step's onExit hook if available
    if (this.currentStep !== stepNum) {
      const prevStepName = this.steps[this.currentStep - 1];
      const prevModule = this.stepModules[prevStepName];
      if (prevModule && typeof prevModule.onExit === 'function') {
        await prevModule.onExit(this);
      }
    }

    this.currentStep = stepNum;

    // Auto-save wizard step to database
    await this.saveWizardStep(stepNum);

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
      // Use absolute path from static root for better reliability
      const modulePath = '/static/js/wizard/step-' + stepName + '.js?v=' + (window.APP_VERSION || '1.0.0');
      console.log('[Wizard] Loading module:', modulePath);
      const module = await import(modulePath);
      this.stepModules[stepName] = module;

      // Initialize module if it has an init function
      if (typeof module.init === 'function') {
        await module.init(this);
      }

      return module;
    } catch (error) {
      console.error('[Wizard] Failed to load step module:', stepName, error);
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
    if (typeof window.showToast === 'function') {
      window.showToast(message, type);
    } else {
      console.log(`[${type.toUpperCase()}] ${message}`);
    }
  }

  /**
   * Save wizard step to database
   */
  async saveWizardStep(step) {
    if (!this.projectId) return;

    try {
      await this.api(`/api/projects/${this.projectId}/wizard`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wizard_step: step })
      });
      console.log('[Wizard] Saved wizard_step:', step);
    } catch (e) {
      console.warn('[Wizard] Failed to save wizard_step:', e);
    }
  }

  /**
   * Show save indicator
   */
  showSaveIndicator() {
    const indicator = document.getElementById('wizard-save-indicator');
    if (indicator) {
      indicator.classList.remove('d-none');
      setTimeout(() => {
        indicator.classList.add('d-none');
      }, 2000);
    }
  }

  /**
   * Save wizard state to database
   */
  async saveWizardState(state, showToast = false) {
    if (!this.projectId) return;

    try {
      // Merge with existing state
      this.wizardState = { ...this.wizardState, ...state };

      await this.api(`/api/projects/${this.projectId}/wizard`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wizard_state: this.wizardState })
      });
      console.log('[Wizard] Saved wizard_state:', this.wizardState);
      this.showSaveIndicator();
      if (showToast) {
        this.showToast('Progress saved', 'success');
      }
    } catch (e) {
      console.warn('[Wizard] Failed to save wizard_state:', e);
      if (showToast) {
        this.showToast('Failed to save progress', 'danger');
      }
    }
  }

  /**
   * Load wizard state from memory (loaded on init)
   */
  loadWizardState() {
    return this.wizardState || {};
  }

  /**
   * Mark project as ready to compile
   */
  async markReady() {
    if (!this.projectId) return;

    try {
      await this.api(`/api/projects/${this.projectId}/wizard`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'ready', wizard_step: 4 })
      });
      console.log('[Wizard] Project marked as ready');
      this.showToast('Project ready to compile!', 'success');
    } catch (e) {
      console.warn('[Wizard] Failed to mark project ready:', e);
    }
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

    // Load wizard state from database
    if (window.wizardExistingProject.wizardState) {
      try {
        wizardInstance.wizardState = typeof window.wizardExistingProject.wizardState === 'string'
          ? JSON.parse(window.wizardExistingProject.wizardState)
          : window.wizardExistingProject.wizardState;
        console.log('[Wizard] Loaded wizard state:', wizardInstance.wizardState);
      } catch (e) {
        console.warn('[Wizard] Failed to parse wizard state:', e);
        wizardInstance.wizardState = {};
      }
    }

    const initialStep = window.wizardExistingProject.initialStep || 1;
    const stepNames = ['', 'Setup', 'Get Clips', 'Arrange', 'Compile'];
    console.log('[Wizard] Loading existing project:', wizardInstance.projectId, 'at step:', initialStep);

    // Show restoration toast
    if (initialStep > 1) {
      wizardInstance.showToast(`Resuming from step ${initialStep}: ${stepNames[initialStep]}`, 'info');
    }


  wizardInstance.gotoStep(initialStep);
  } else {
    wizardInstance.gotoStep(1);
  }

  return wizardInstance;
}export function getWizard() {
  return wizardInstance;
}
