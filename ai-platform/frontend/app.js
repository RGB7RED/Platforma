(() => {
  const railwayHostPattern = /^[^/]+\.up\.railway\.app(?:\/|$)/i;
  const normalizeApiBaseUrl = (value) => {
    if (typeof value !== 'string') {
      return '';
    }
    const trimmed = value.trim();
    if (!trimmed) {
      return '';
    }
    if (trimmed.toLowerCase().startsWith('http://')) {
      return `https://${trimmed.slice(7)}`;
    }
    if (railwayHostPattern.test(trimmed) && !/^[a-z]+:\/\//i.test(trimmed)) {
      return `https://${trimmed}`;
    }
    return trimmed;
  };
  const isMixedContentUrl = (value) =>
    typeof value === 'string' &&
    window.location.protocol === 'https:' &&
    value.toLowerCase().startsWith('http://');
  const formatNetworkError = (url) => {
    if (isMixedContentUrl(url)) {
      return 'network_error: API_BASE_URL must be HTTPS';
    }
    return 'network_error: Unable to reach the API.';
  };

  const resolveApiBaseUrl = () => {
    const configValue = window.__APP_CONFIG__?.API_BASE_URL;
    if (typeof configValue === 'string' && configValue.trim()) {
      return normalizeApiBaseUrl(configValue);
    }
    const metaValue = document.querySelector('meta[name="api-base-url"]')?.content;
    if (typeof metaValue === 'string' && metaValue.trim()) {
      return normalizeApiBaseUrl(metaValue);
    }
    return '';
  };

  const resolveAuthMode = () => {
    const configValue = window.__APP_CONFIG__?.AUTH_MODE;
    if (typeof configValue === 'string' && configValue.trim()) {
      return configValue.trim().toLowerCase();
    }
    const metaValue = document.querySelector('meta[name="auth-mode"]')?.content;
    if (typeof metaValue === 'string' && metaValue.trim()) {
      return metaValue.trim().toLowerCase();
    }
    return 'apikey';
  };

  const AUTH_MODE_APIKEY = 'apikey';
  const AUTH_MODE_AUTH = 'auth';
  const AUTH_MODE_HYBRID = 'hybrid';
  const normalizeAuthMode = (value) => {
    if (!value) {
      return AUTH_MODE_APIKEY;
    }
    const normalized = value.trim().toLowerCase();
    if (normalized === 'apikey' || normalized === 'api_key') {
      return AUTH_MODE_APIKEY;
    }
    if ([AUTH_MODE_APIKEY, AUTH_MODE_AUTH, AUTH_MODE_HYBRID].includes(normalized)) {
      return normalized;
    }
    return AUTH_MODE_APIKEY;
  };

  const runtimeConfig = {
    apiBaseUrl: normalizeApiBaseUrl(resolveApiBaseUrl()),
    wsBaseUrl: '',
    authMode: normalizeAuthMode(resolveAuthMode()),
    googleOAuthEnabled: false
  };

  const getAuthMode = () => runtimeConfig.authMode;
  const isAuthEnabled = () => {
    const mode = getAuthMode();
    return mode === AUTH_MODE_AUTH || mode === AUTH_MODE_HYBRID;
  };
  const isApiKeyEnabled = () => {
    const mode = getAuthMode();
    return mode === AUTH_MODE_APIKEY || mode === AUTH_MODE_HYBRID;
  };
  const isGoogleAuthEnabled = () => runtimeConfig.googleOAuthEnabled;
  const normalizeBaseUrl = (value) => value.replace(/\/+$/, '');
  const normalizePath = (value) => (value.startsWith('/') ? value : `/${value}`);
  const buildApiUrl = (path) => {
    const resolvedPath = normalizePath(path);
    if (!runtimeConfig.apiBaseUrl) {
      return resolvedPath;
    }
    return `${normalizeBaseUrl(runtimeConfig.apiBaseUrl)}${resolvedPath}`;
  };
  const buildWebSocketUrl = (taskId) => {
    const wsPath = `/ws/${taskId}`;
    const fallbackProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsBaseUrl = runtimeConfig.wsBaseUrl
      ? normalizeBaseUrl(runtimeConfig.wsBaseUrl)
      : runtimeConfig.apiBaseUrl
        ? normalizeBaseUrl(runtimeConfig.apiBaseUrl)
        : '';
    if (!wsBaseUrl) {
      return `${fallbackProtocol}://${window.location.host}${wsPath}`;
    }
    try {
      const apiUrl = new URL(wsBaseUrl);
      const wsProtocol = apiUrl.protocol === 'https:' ? 'wss:' : 'ws:';
      const basePath = apiUrl.pathname.replace(/\/+$/, '');
      return `${wsProtocol}//${apiUrl.host}${basePath}${wsPath}`;
    } catch (error) {
      return `${fallbackProtocol}://${window.location.host}${wsPath}`;
    }
  };

  const appendApiKeyQuery = (url) => {
    const apiKey = getStoredApiKey();
    if (!apiKey) {
      return url;
    }
    const separator = url.includes('?') ? '&' : '?';
    return `${url}${separator}api_key=${encodeURIComponent(apiKey)}`;
  };

  const appendTokenQuery = (url, token) => {
    if (!token) {
      return url;
    }
    const separator = url.includes('?') ? '&' : '?';
    return `${url}${separator}token=${encodeURIComponent(token)}`;
  };

  const POLL_INTERVAL_MS = 2000;
  const POLL_SLOW_INTERVAL_MS = 4000;
  const POLL_TIMEOUT_MS = 3 * 60 * 1000;
  const TERMINAL_STATUSES = new Set(['completed', 'failed', 'error']);
  const RESEARCH_CHAT_STATUSES = new Set(['awaiting_user', 'waiting_for_user', 'needs_input']);
  const AWAITING_USER_STATUSES = new Set(['awaiting_user', 'waiting_for_user']);
  const RESEARCH_STAGES = new Set(['research', 'interactive_research']);
  const API_KEY_STORAGE_KEY = 'aiPlatformApiKey';
  const ACCESS_TOKEN_STORAGE_KEY = 'aiPlatformAccessToken';
  const REFRESH_TOKEN_STORAGE_KEY = 'aiPlatformRefreshToken';
  const debugEnabled = new URLSearchParams(window.location.search).get('debug') === '1';

  const elements = {
    welcomeScreen: document.getElementById('welcomeScreen'),
    taskCreation: document.getElementById('taskCreation'),
    taskProgress: document.getElementById('taskProgress'),
    taskResults: document.getElementById('taskResults'),
    previousTasks: document.getElementById('previousTasks'),
    startTaskBtn: document.getElementById('startTaskBtn'),
    viewTasksBtn: document.getElementById('viewTasksBtn'),
    startFirstTaskBtn: document.getElementById('startFirstTaskBtn'),
    newTaskFromResultsBtn: document.getElementById('newTaskFromResultsBtn'),
    backToMainBtn: document.getElementById('backToMainBtn'),
    cancelTaskBtn: document.getElementById('cancelTaskBtn'),
    submitTaskBtn: document.getElementById('submitTaskBtn'),
    refreshProgressBtn: document.getElementById('refreshProgressBtn'),
    taskDescription: document.getElementById('taskDescription'),
    charCount: document.getElementById('charCount'),
    interactiveDisabledHint: document.getElementById('interactiveDisabledHint'),
    legacyPromptGroup: document.getElementById('legacyPromptGroup'),
    intakeChatPanel: document.getElementById('intakeChatPanel'),
    intakeChatHistory: document.getElementById('intakeChatHistory'),
    intakeChatInput: document.getElementById('intakeChatInput'),
    intakeChatSendBtn: document.getElementById('intakeChatSendBtn'),
    intakeChatHint: document.getElementById('intakeChatHint'),
    intakeChatStatus: document.getElementById('intakeChatStatus'),
    codexVersion: document.getElementById('codexVersion'),
    templateSelect: document.getElementById('templateSelect'),
    templateWarning: document.getElementById('templateWarning'),
    projectSelect: document.getElementById('projectSelect'),
    currentTaskId: document.getElementById('currentTaskId'),
    progressBarFill: document.getElementById('progressBarFill'),
    progressPercentage: document.getElementById('progressPercentage'),
    progressTime: document.getElementById('progressTime'),
    currentStage: document.getElementById('currentStage'),
    taskStatus: document.getElementById('taskStatus'),
    apiBaseUrl: document.getElementById('apiBaseUrl'),
    apiBaseUrlStatus: document.getElementById('apiBaseUrlStatus'),
    authPanel: document.getElementById('authPanel'),
    authStatus: document.getElementById('authStatus'),
    authModeIndicator: document.getElementById('authModeIndicator'),
    authLoginFields: document.getElementById('authLoginFields'),
    authEmailInput: document.getElementById('authEmailInput'),
    authPasswordInput: document.getElementById('authPasswordInput'),
    authLoginBtn: document.getElementById('authLoginBtn'),
    authRegisterBtn: document.getElementById('authRegisterBtn'),
    authLogoutBtn: document.getElementById('authLogoutBtn'),
    authError: document.getElementById('authError'),
    authTokenStatus: document.getElementById('authTokenStatus'),
    authLastError: document.getElementById('authLastError'),
    accessTokenGroup: document.getElementById('accessTokenGroup'),
    apiKeyGroup: document.getElementById('apiKeyGroup'),
    apiKeyInput: document.getElementById('apiKeyInput'),
    saveApiKeyBtn: document.getElementById('saveApiKeyBtn'),
    accessTokenInput: document.getElementById('accessTokenInput'),
    saveAccessTokenBtn: document.getElementById('saveAccessTokenBtn'),
    googleSignInBtn: document.getElementById('googleSignInBtn'),
    taskError: document.getElementById('taskError'),
    clarificationPanel: document.getElementById('clarificationPanel'),
    clarificationMessage: document.getElementById('clarificationMessage'),
    clarificationForm: document.getElementById('clarificationForm'),
    submitClarificationBtn: document.getElementById('submitClarificationBtn'),
    resumeTaskBtn: document.getElementById('resumeTaskBtn'),
    researchChatPanel: document.getElementById('researchChatPanel'),
    researchChatHistory: document.getElementById('researchChatHistory'),
    researchChatInput: document.getElementById('researchChatInput'),
    researchChatSendBtn: document.getElementById('researchChatSendBtn'),
    researchChatHint: document.getElementById('researchChatHint'),
    manualStepPanel: document.getElementById('manualStepPanel'),
    manualStepMessage: document.getElementById('manualStepMessage'),
    manualStepStage: document.getElementById('manualStepStage'),
    manualStepReviewStatus: document.getElementById('manualStepReviewStatus'),
    manualStepPreview: document.getElementById('manualStepPreview'),
    nextStepBtn: document.getElementById('nextStepBtn'),
    taskIdInput: document.getElementById('taskIdInput'),
    loadTaskBtn: document.getElementById('loadTaskBtn'),
    copyTaskIdBtn: document.getElementById('copyTaskIdBtn'),
    inspectorTabs: document.getElementById('inspectorTabs'),
    statePanel: document.getElementById('statePanel'),
    stateTable: document.getElementById('stateTable'),
    stateError: document.getElementById('stateError'),
    eventsPanel: document.getElementById('eventsPanel'),
    eventsList: document.getElementById('eventsList'),
    eventsError: document.getElementById('eventsError'),
    artifactsPanel: document.getElementById('artifactsPanel'),
    artifactsList: document.getElementById('artifactsList'),
    artifactsError: document.getElementById('artifactsError'),
    artifactTypeInput: document.getElementById('artifactTypeInput'),
    artifactFilterBtn: document.getElementById('artifactFilterBtn'),
    resultJson: document.getElementById('resultJson'),
    resultStatus: document.getElementById('resultStatus'),
    filesCount: document.getElementById('filesCount'),
    artifactsCount: document.getElementById('artifactsCount'),
    iterationsCount: document.getElementById('iterationsCount'),
    timeTaken: document.getElementById('timeTaken'),
    latestReviewResult: document.getElementById('latestReviewResult'),
    rerunReviewBtn: document.getElementById('rerunReviewBtn'),
    downloadZipBtn: document.getElementById('downloadZipBtn'),
    downloadGitExportBtn: document.getElementById('downloadGitExportBtn'),
    fileCategories: document.getElementById('fileCategories'),
    fileList: document.getElementById('fileList'),
    filePreview: document.getElementById('filePreview'),
    previewFileName: document.getElementById('previewFileName'),
    fileContentPreview: document.getElementById('fileContentPreview'),
    copyFileBtn: document.getElementById('copyFileBtn'),
    loadingOverlay: document.getElementById('loadingOverlay'),
    loadingMessage: document.getElementById('loadingMessage'),
    loadingSubtext: document.getElementById('loadingSubtext'),
    notificationToast: document.getElementById('notificationToast'),
    toastIcon: document.getElementById('toastIcon'),
    toastMessage: document.getElementById('toastMessage'),
    projectNameInput: document.getElementById('projectNameInput'),
    projectTemplateSelect: document.getElementById('projectTemplateSelect'),
    projectTemplateWarning: document.getElementById('projectTemplateWarning'),
    createProjectBtn: document.getElementById('createProjectBtn'),
    githubProjectSelect: document.getElementById('githubProjectSelect'),
    githubRepoInput: document.getElementById('githubRepoInput'),
    githubDefaultBranchInput: document.getElementById('githubDefaultBranchInput'),
    githubTokenInput: document.getElementById('githubTokenInput'),
    connectGithubBtn: document.getElementById('connectGithubBtn'),
    testGithubBtn: document.getElementById('testGithubBtn'),
    githubConnectStatus: document.getElementById('githubConnectStatus'),
    githubTestStatus: document.getElementById('githubTestStatus'),
    refreshDashboardBtn: document.getElementById('refreshDashboardBtn'),
    projectsList: document.getElementById('projectsList'),
    projectsEmpty: document.getElementById('projectsEmpty'),
    projectError: document.getElementById('projectError'),
    tasksList: document.getElementById('tasksList'),
    tasksEmpty: document.getElementById('tasksEmpty'),
    createPrBtn: document.getElementById('createPrBtn'),
    prCreateStatus: document.getElementById('prCreateStatus'),
    debugPanel: document.getElementById('debugPanel'),
    debugApiBaseUrl: document.getElementById('debugApiBaseUrl'),
    debugTaskId: document.getElementById('debugTaskId'),
    debugTaskStatus: document.getElementById('debugTaskStatus'),
    debugCanStart: document.getElementById('debugCanStart'),
    debugTaskStage: document.getElementById('debugTaskStage'),
    debugResearchChatCount: document.getElementById('debugResearchChatCount'),
    debugLastAssistant: document.getElementById('debugLastAssistant'),
    debugLastUser: document.getElementById('debugLastUser')
  };

  let currentTaskId = null;
  let pollStartTime = null;
  let inMemoryAccessToken = '';
  let authUser = null;
  let refreshPromise = null;
  let lastAuthError = '';
  let pollingIntervals = {
    status: null,
    state: null,
    events: null,
    artifacts: null,
    files: null
  };
  let lastEventSignature = '';
  let lastArtifactSignature = '';
  let lastQuestionsSignature = '';
  let lastResearchChatSignature = '';
  let artifactTypeFilter = '';
  let activeInspectorTab = 'state';
  let latestFilesTotal = null;
  let latestArtifactsTotal = null;
  let researchChatEmptyMessage = 'No chat messages yet.';
  let intakeChatEmptyMessage = 'Напишите первое сообщение, чтобы начать.';
  let activeFileCategory = 'all';
  let activeFilePath = '';
  let activeFileContent = '';
  let activeSocket = null;
  let latestTaskSnapshot = null;
  let latestQuestionsPayload = null;
  let intakeCanStart = false;
  let missingAuthMessage = 'Please sign in to continue.';
  let cachedProjects = [];
  let cachedTasks = [];
  let projectLookup = new Map();

  const hydrateStoredTokens = () => {
    const storedToken = window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
    inMemoryAccessToken = typeof storedToken === 'string' ? storedToken.trim() : '';
  };

  const sections = [
    elements.welcomeScreen,
    elements.taskCreation,
    elements.taskProgress,
    elements.taskResults,
    elements.previousTasks
  ].filter(Boolean);

  const showSection = (section) => {
    sections.forEach((item) => {
      if (!item) {
        return;
      }
      item.classList.toggle('hidden', item !== section);
    });
  };

  const showResultsWithInspector = () => {
    sections.forEach((item) => {
      if (!item) {
        return;
      }
      const shouldShow =
        item === elements.taskProgress || item === elements.taskResults;
      item.classList.toggle('hidden', !shouldShow);
    });
  };

  const showToast = (message, icon = 'ℹ️') => {
    if (!elements.notificationToast) {
      return;
    }
    elements.toastIcon.textContent = icon;
    elements.toastMessage.textContent = message;
    elements.notificationToast.classList.remove('hidden');
    setTimeout(() => {
      elements.notificationToast.classList.add('hidden');
    }, 4000);
  };

  const setLoading = (isLoading, message = 'Processing your task...', subtext = '') => {
    if (!elements.loadingOverlay) {
      return;
    }
    elements.loadingMessage.textContent = message;
    elements.loadingSubtext.textContent = subtext;
    elements.loadingOverlay.classList.toggle('hidden', !isLoading);
  };

  const setSubmitDisabled = (isDisabled) => {
    if (elements.submitTaskBtn) {
      elements.submitTaskBtn.disabled = isDisabled;
    }
  };

  const updateCharCount = () => {
    if (!elements.taskDescription || !elements.charCount) {
      return;
    }
    elements.charCount.textContent = String(elements.taskDescription.value.length);
  };

  const updateApiBaseUrl = () => {
    const resolvedValue = runtimeConfig.apiBaseUrl || '(same origin)';
    if (elements.apiBaseUrl) {
      elements.apiBaseUrl.textContent = resolvedValue;
    }
    if (elements.apiBaseUrlStatus) {
      elements.apiBaseUrlStatus.textContent = resolvedValue;
    }
  };

  const updateAuthModeIndicator = () => {
    if (!elements.authModeIndicator) {
      return;
    }
    elements.authModeIndicator.textContent = getAuthMode() || '-';
  };

  const updateAuthDiagnostics = () => {
    if (elements.authTokenStatus) {
      elements.authTokenStatus.textContent = getStoredAccessToken() ? 'present' : 'absent';
    }
    if (elements.authLastError) {
      elements.authLastError.textContent = lastAuthError || '';
    }
  };

  const updateAuthStatus = () => {
    if (!elements.authStatus) {
      return;
    }
    if (getStoredAccessToken()) {
      const label = authUser?.email ? `Signed in as ${authUser.email}` : 'Signed in.';
      elements.authStatus.textContent = label;
      if (elements.authLogoutBtn) {
        elements.authLogoutBtn.classList.remove('hidden');
      }
      if (elements.authLoginFields) {
        elements.authLoginFields.classList.add('hidden');
      }
      updateAuthDiagnostics();
      return;
    }
    elements.authStatus.textContent = 'Not signed in.';
    if (elements.authLogoutBtn) {
      elements.authLogoutBtn.classList.add('hidden');
    }
    if (elements.authLoginFields) {
      elements.authLoginFields.classList.remove('hidden');
    }
    updateAuthDiagnostics();
  };

  const updateAuthModeVisibility = () => {
    const authEnabled = isAuthEnabled();
    const apiKeyEnabled = isApiKeyEnabled();
    const googleAuthEnabled = isGoogleAuthEnabled();
    if (elements.authPanel) {
      elements.authPanel.classList.toggle('hidden', !authEnabled);
    }
    if (elements.apiKeyGroup) {
      elements.apiKeyGroup.classList.toggle('hidden', !apiKeyEnabled);
    }
    if (elements.accessTokenGroup) {
      const shouldShowAccessTokenInput = getAuthMode() === AUTH_MODE_HYBRID;
      elements.accessTokenGroup.classList.toggle('hidden', !shouldShowAccessTokenInput);
    }
    if (elements.googleSignInBtn) {
      elements.googleSignInBtn.classList.toggle('hidden', !(authEnabled && googleAuthEnabled));
    }
    if (elements.authLoginFields) {
      elements.authLoginFields.classList.toggle('hidden', !authEnabled);
    }
    updateAuthStatus();
    updateMissingAuthMessage();
  };

  const getStoredApiKey = () => {
    if (!isApiKeyEnabled()) {
      return '';
    }
    const value = window.localStorage.getItem(API_KEY_STORAGE_KEY);
    return typeof value === 'string' ? value.trim() : '';
  };

  const setStoredApiKey = (value) => {
    if (!isApiKeyEnabled()) {
      return;
    }
    const normalized = value.trim();
    if (!normalized) {
      window.localStorage.removeItem(API_KEY_STORAGE_KEY);
      updateApiKeyInputs('');
      return;
    }
    window.localStorage.setItem(API_KEY_STORAGE_KEY, normalized);
    updateApiKeyInputs(normalized);
  };

  const getStoredAccessToken = () => {
    return inMemoryAccessToken;
  };

  const getStoredRefreshToken = () => {
    const value = window.localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY);
    return typeof value === 'string' ? value.trim() : '';
  };

  const setStoredRefreshToken = (value) => {
    const normalized = value?.trim ? value.trim() : '';
    if (!normalized) {
      window.localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, normalized);
  };

  const setStoredAccessToken = (value, user = null) => {
    const normalized = value.trim();
    inMemoryAccessToken = normalized;
    if (!normalized) {
      window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
      authUser = null;
      setStoredRefreshToken('');
    } else {
      window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, normalized);
      if (user !== null) {
        authUser = user;
      } else {
        authUser = authUser || null;
      }
    }
    updateAccessTokenInputs(normalized);
    updateAuthStatus();
  };

  const updateMissingAuthMessage = () => {
    missingAuthMessage = isAuthEnabled()
      ? 'Please sign in to continue.'
      : 'Please save your API key before continuing.';
  };

  const updateApiKeyInputs = (value) => {
    if (elements.apiKeyInput) {
      elements.apiKeyInput.value = value || '';
    }
  };

  const updateAccessTokenInputs = (value) => {
    if (elements.accessTokenInput) {
      elements.accessTokenInput.value = value || '';
    }
  };

  const syncAccessTokenFromHash = () => {
    if (!window.location.hash) {
      return;
    }
    const hash = window.location.hash.startsWith('#')
      ? window.location.hash.slice(1)
      : window.location.hash;
    const params = new URLSearchParams(hash);
    const accessToken = params.get('access_token');
    if (!accessToken) {
      return;
    }
    setStoredAccessToken(accessToken);
    setAuthError('');
    showToast('Signed in with Google.', '✅');
    window.history.replaceState(
      null,
      document.title,
      `${window.location.pathname}${window.location.search}`
    );
  };

  const hasAuthCredentials = () =>
    Boolean(getStoredAccessToken() || (isApiKeyEnabled() && getStoredApiKey()));

  const fetchRuntimeConfig = async () => {
    const bootstrapBase = resolveApiBaseUrl();
    const configUrl = bootstrapBase
      ? `${normalizeBaseUrl(bootstrapBase)}${normalizePath('/api/config')}`
      : '/api/config';
    try {
      const response = await fetch(configUrl, { credentials: 'include' });
      if (!response.ok) {
        return;
      }
      const data = await response.json();
      runtimeConfig.authMode = normalizeAuthMode(data?.auth_mode || runtimeConfig.authMode);
      runtimeConfig.apiBaseUrl = normalizeApiBaseUrl(
        typeof data?.api_base_url === 'string' && data.api_base_url.trim()
          ? data.api_base_url.trim()
          : runtimeConfig.apiBaseUrl
      );
      runtimeConfig.wsBaseUrl =
        typeof data?.ws_base_url === 'string' && data.ws_base_url.trim()
          ? data.ws_base_url.trim()
          : runtimeConfig.wsBaseUrl;
      runtimeConfig.googleOAuthEnabled = Boolean(data?.google_oauth_enabled);
    } catch (error) {
      // Ignore config fetch errors and fallback to meta/defaults.
    } finally {
      updateApiBaseUrl();
      updateAuthModeIndicator();
      updateAuthModeVisibility();
      updateMissingAuthMessage();
      updateIntakeVisibility(resolveInteractiveResearchEnabled(latestTaskSnapshot));
      updateStartProcessingState({ canStart: intakeCanStart, interactiveEnabled: resolveInteractiveResearchEnabled(latestTaskSnapshot) });
    }
  };

  const setTemplateOptions = (templates) => {
    const templateSelects = [elements.templateSelect, elements.projectTemplateSelect].filter(Boolean);
    templateSelects.forEach((select) => {
      select.innerHTML = '';
      const noneOption = document.createElement('option');
      noneOption.value = '';
      noneOption.textContent = select === elements.projectTemplateSelect ? 'No template' : 'None';
      select.appendChild(noneOption);

      templates.forEach((template) => {
        if (!template || !template.template_id) {
          return;
        }
        const option = document.createElement('option');
        option.value = template.template_id;
        const description = template.description ? ` — ${template.description}` : '';
        option.textContent = `${template.template_id}${description}`;
        select.appendChild(option);
      });
    });
  };

  const setTemplateWarning = (message) => {
    const warnings = [elements.templateWarning, elements.projectTemplateWarning].filter(Boolean);
    const text = message ? String(message) : '';
    warnings.forEach((warning) => {
      warning.textContent = text;
      warning.classList.toggle('hidden', !text);
    });
  };

  const setProjectOptions = (projects) => {
    if (!elements.projectSelect && !elements.githubProjectSelect) {
      return;
    }
    if (elements.projectSelect) {
      elements.projectSelect.innerHTML = '';
      const noneOption = document.createElement('option');
      noneOption.value = '';
      noneOption.textContent = 'No project';
      elements.projectSelect.appendChild(noneOption);

      projects.forEach((project) => {
        if (!project || !project.id) {
          return;
        }
        const option = document.createElement('option');
        option.value = project.id;
        const templateSuffix = project.template_id ? ` • ${project.template_id}` : '';
        option.textContent = `${project.name}${templateSuffix}`;
        elements.projectSelect.appendChild(option);
      });
    }
    if (elements.githubProjectSelect) {
      elements.githubProjectSelect.innerHTML = '';
      const noneOption = document.createElement('option');
      noneOption.value = '';
      noneOption.textContent = 'Select project';
      elements.githubProjectSelect.appendChild(noneOption);
      projects.forEach((project) => {
        if (!project || !project.id) {
          return;
        }
        const option = document.createElement('option');
        option.value = project.id;
        option.textContent = project.name || 'Untitled project';
        elements.githubProjectSelect.appendChild(option);
      });
    }
  };

  const loadTemplates = async () => {
    if (!elements.templateSelect && !elements.projectTemplateSelect) {
      return;
    }
    const warningMessage = 'Templates unavailable (check backend templates deployment)';
    setTemplateWarning('');
    try {
      const response = await apiFetch(buildApiUrl('/api/templates'));
      if (response.status === 401) {
        setTemplateOptions([]);
        setTemplateWarning(warningMessage);
        if (isAuthEnabled()) {
          updateAuthStatus();
          setAuthError('Sign in to load templates.');
        }
        return;
      }
      if (!response.ok) {
        throw new Error('Templates unavailable');
      }
      const data = await response.json();
      const templates = Array.isArray(data.templates) ? data.templates : [];
      setTemplateOptions(templates);
      if (templates.length === 0) {
        setTemplateWarning(warningMessage);
      } else {
        setTemplateWarning('');
      }
    } catch (error) {
      setTemplateOptions([]);
      setTemplateWarning(warningMessage);
    }
  };

  const getAuthUserId = () => authUser?.id || authUser?.user_id || null;

  const setProjectError = (message) => {
    if (!elements.projectError) {
      return;
    }
    const text = message ? String(message) : '';
    elements.projectError.textContent = text;
    elements.projectError.classList.toggle('hidden', !text);
  };

  const setGithubConnectStatus = (message, tone = '') => {
    if (!elements.githubConnectStatus) {
      return;
    }
    const text = message ? String(message) : '';
    elements.githubConnectStatus.textContent = text;
    elements.githubConnectStatus.classList.toggle('hidden', !text);
    elements.githubConnectStatus.classList.toggle('error-message', tone === 'error');
  };

  const setGithubTestStatus = (message, tone = '') => {
    if (!elements.githubTestStatus) {
      return;
    }
    const text = message ? String(message) : '';
    elements.githubTestStatus.textContent = text;
    elements.githubTestStatus.classList.toggle('hidden', !text);
    elements.githubTestStatus.classList.toggle('error-message', tone === 'error');
  };

  const setPrCreateStatus = (message, tone = '') => {
    if (!elements.prCreateStatus) {
      return;
    }
    const text = message ? String(message) : '';
    elements.prCreateStatus.textContent = text;
    elements.prCreateStatus.classList.toggle('hidden', !text);
    elements.prCreateStatus.classList.toggle('error-message', tone === 'error');
  };

  const fetchProjects = async () => {
    const userId = getAuthUserId();
    if (!userId) {
      setProjectError('Sign in to view projects.');
      return [];
    }
    try {
      const response = await apiFetch(buildApiUrl('/api/projects'));
      if (response.status === 401 || response.status === 403) {
        setProjectError('Sign in to view projects.');
        return [];
      }
      if (!response.ok) {
        throw new Error(`Projects unavailable (${response.status})`);
      }
      const data = await response.json();
      setProjectError('');
      return Array.isArray(data.projects) ? data.projects : [];
    } catch (error) {
      setProjectError(error?.message || 'Unable to load projects.');
      return [];
    }
  };

  const fetchTasksForUser = async () => {
    const userId = getAuthUserId();
    if (!userId) {
      return [];
    }
    try {
      const response = await apiFetch(buildApiUrl(`/api/users/${userId}/tasks?limit=50`));
      if (response.status === 401 || response.status === 403) {
        return [];
      }
      if (!response.ok) {
        throw new Error(`Tasks unavailable (${response.status})`);
      }
      const data = await response.json();
      return Array.isArray(data.tasks) ? data.tasks : [];
    } catch (error) {
      return [];
    }
  };

  const renderProjects = (projects, tasksByProject) => {
    if (!elements.projectsList || !elements.projectsEmpty) {
      return;
    }
    elements.projectsList.innerHTML = '';
    elements.projectsEmpty.classList.toggle('hidden', projects.length > 0);
    if (!projects.length) {
      return;
    }
    projects.forEach((project) => {
      const item = document.createElement('div');
      item.className = 'task-history-item';

      const info = document.createElement('div');
      info.className = 'task-history-info';
      const title = document.createElement('h4');
      title.textContent = project.name || 'Untitled project';
      const meta = document.createElement('div');
      meta.className = 'task-history-meta';
      const taskCount = tasksByProject.get(project.id)?.length || 0;
      const templateLabel = project.template_id ? `Template: ${project.template_id}` : 'Template: none';
      const repoLabel = project.repo_full_name
        ? `Repo: ${project.repo_full_name}${project.default_branch ? ` (${project.default_branch})` : ''}`
        : 'Repo: not connected';
      meta.textContent = `${templateLabel} • ${repoLabel} • ${taskCount} task${taskCount === 1 ? '' : 's'} • ${formatShortDate(project.created_at)}`;

      info.appendChild(title);
      info.appendChild(meta);
      item.appendChild(info);
      elements.projectsList.appendChild(item);
    });
  };

  const renderTasks = (tasks, projects) => {
    if (!elements.tasksList || !elements.tasksEmpty) {
      return;
    }
    elements.tasksList.innerHTML = '';
    elements.tasksEmpty.classList.toggle('hidden', tasks.length > 0);
    if (!tasks.length) {
      return;
    }

    const projectNameById = new Map(projects.map((project) => [project.id, project.name]));
    const grouped = tasks.reduce((acc, task) => {
      const key = task.project_id || 'unassigned';
      if (!acc.has(key)) {
        acc.set(key, []);
      }
      acc.get(key).push(task);
      return acc;
    }, new Map());

    grouped.forEach((groupTasks, projectId) => {
      const header = document.createElement('h4');
      header.textContent =
        projectId === 'unassigned'
          ? 'Unassigned'
          : projectNameById.get(projectId) || 'Unknown project';
      elements.tasksList.appendChild(header);

      groupTasks.forEach((task) => {
        const item = document.createElement('div');
        item.className = 'task-history-item';

        const info = document.createElement('div');
        info.className = 'task-history-info';
        const title = document.createElement('h4');
        title.textContent = task.description || 'Untitled task';
        const meta = document.createElement('div');
        meta.className = 'task-history-meta';
        const status = task.status || 'unknown';
        meta.textContent = `${status} • ${formatShortDate(task.created_at || task.updated_at)}`;
        info.appendChild(title);
        info.appendChild(meta);

        const actions = document.createElement('div');
        actions.className = 'task-history-actions';
        const openButton = document.createElement('button');
        openButton.className = 'secondary-btn';
        openButton.type = 'button';
        openButton.textContent = 'Open';
        openButton.addEventListener('click', () => {
          if (!ensureAuthForAction()) {
            return;
          }
          activateTask(task.id || task.task_id);
        });
        actions.appendChild(openButton);

        item.appendChild(info);
        item.appendChild(actions);
        elements.tasksList.appendChild(item);
      });
    });
  };

  const refreshDashboard = async ({ silent = false } = {}) => {
    if (!hasAuthCredentials()) {
      if (!silent) {
        showToast(missingAuthMessage, '⚠️');
      }
      cachedProjects = [];
      cachedTasks = [];
      projectLookup = new Map();
      setProjectOptions([]);
      renderProjects([], new Map());
      renderTasks([], []);
      setCreatePrEnabled(false);
      return;
    }
    const [projects, tasks] = await Promise.all([fetchProjects(), fetchTasksForUser()]);
    cachedProjects = projects;
    cachedTasks = tasks;
    projectLookup = new Map(projects.map((project) => [project.id, project]));
    setProjectOptions(projects);
    const tasksByProject = tasks.reduce((acc, task) => {
      const key = task.project_id || 'unassigned';
      if (!acc.has(key)) {
        acc.set(key, []);
      }
      acc.get(key).push(task);
      return acc;
    }, new Map());
    renderProjects(projects, tasksByProject);
    renderTasks(tasks, projects);
    updateCreatePrState();
  };

  const createProject = async () => {
    const userId = getAuthUserId();
    if (!userId) {
      showToast('Please sign in to create projects.', '⚠️');
      return;
    }
    const name = elements.projectNameInput?.value.trim();
    if (!name) {
      showToast('Please provide a project name.', '⚠️');
      return;
    }
    const templateId = elements.projectTemplateSelect?.value?.trim();
    const payload = { name };
    if (templateId) {
      payload.template_id = templateId;
    }
    try {
      const response = await apiFetch(buildApiUrl('/api/projects'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });
      if (!response.ok) {
        const message = response.status === 401 || response.status === 403
          ? 'Sign in to create projects.'
          : `Project creation failed (${response.status})`;
        throw new Error(message);
      }
      await response.json();
      if (elements.projectNameInput) {
        elements.projectNameInput.value = '';
      }
      showToast('Project created.', '✅');
      await refreshDashboard();
    } catch (error) {
      showToast(error?.message || 'Unable to create project.', '⚠️');
    }
  };

  const connectGithubProject = async () => {
    const userId = getAuthUserId();
    if (!userId) {
      showToast('Please sign in to connect GitHub.', '⚠️');
      return;
    }
    const projectId = elements.githubProjectSelect?.value?.trim();
    if (!projectId) {
      showToast('Select a project to connect.', '⚠️');
      return;
    }
    const repoFullName = elements.githubRepoInput?.value?.trim();
    if (!repoFullName) {
      showToast('Enter a GitHub repository (owner/name).', '⚠️');
      return;
    }
    const accessToken = elements.githubTokenInput?.value?.trim();
    if (!accessToken) {
      showToast('Provide a GitHub access token.', '⚠️');
      return;
    }
    const payload = {
      repo_full_name: repoFullName,
      access_token: accessToken
    };
    const defaultBranch = elements.githubDefaultBranchInput?.value?.trim();
    if (defaultBranch) {
      payload.default_branch = defaultBranch;
    }
    setGithubConnectStatus('');
    try {
      const response = await apiFetch(buildApiUrl(`/api/projects/${projectId}/connect-github`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });
      if (!response.ok) {
        const message = response.status === 401 || response.status === 403
          ? 'Sign in to connect GitHub.'
          : `GitHub connect failed (${response.status})`;
        throw new Error(message);
      }
      await response.json();
      showToast('GitHub repository connected.', '✅');
      setGithubConnectStatus('GitHub repository connected.');
      await refreshDashboard();
    } catch (error) {
      const message = error?.message || 'Unable to connect GitHub.';
      setGithubConnectStatus(message, 'error');
      showToast(message, '⚠️');
    }
  };

  const testGithubConnection = async () => {
    const userId = getAuthUserId();
    if (!userId) {
      showToast('Please sign in to test GitHub.', '⚠️');
      return;
    }
    const projectId = elements.githubProjectSelect?.value?.trim();
    if (!projectId) {
      showToast('Select a project to test.', '⚠️');
      return;
    }
    const repoFullName = elements.githubRepoInput?.value?.trim();
    if (!repoFullName) {
      showToast('Enter a GitHub repository (owner/name).', '⚠️');
      return;
    }
    const accessToken = elements.githubTokenInput?.value?.trim();
    if (!accessToken) {
      showToast('Provide a GitHub access token.', '⚠️');
      return;
    }
    const payload = {
      repo_full_name: repoFullName,
      access_token: accessToken
    };
    const defaultBranch = elements.githubDefaultBranchInput?.value?.trim();
    if (defaultBranch) {
      payload.default_branch = defaultBranch;
    }
    setGithubTestStatus('');
    try {
      const response = await apiFetch(buildApiUrl(`/api/projects/${projectId}/test-github`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });
      if (!response.ok) {
        const errorPayload = await readResponseJson(response);
        const message = response.status === 401 || response.status === 403
          ? 'Sign in to test GitHub.'
          : formatPrErrorMessage(errorPayload, response.status);
        throw new Error(message);
      }
      const data = await response.json();
      const branchInfo = data?.default_branch ? `Default branch: ${data.default_branch}` : 'Default branch resolved.';
      const message = `GitHub connection ok. ${branchInfo}`;
      setGithubTestStatus(message);
      showToast('GitHub connection verified.', '✅');
    } catch (error) {
      const message = error?.message || 'Unable to test GitHub.';
      setGithubTestStatus(message, 'error');
      showToast(message, '⚠️');
    }
  };

  const applyProjectTemplate = () => {
    if (!elements.projectSelect || !elements.templateSelect) {
      return;
    }
    const projectId = elements.projectSelect.value;
    if (!projectId) {
      return;
    }
    const project = projectLookup.get(projectId);
    if (project?.template_id) {
      elements.templateSelect.value = project.template_id;
    }
  };

  const buildAuthHeaders = (extraHeaders = {}) => {
    const headers = { ...extraHeaders };
    const accessToken = getStoredAccessToken();
    if (accessToken) {
      headers.Authorization = `Bearer ${accessToken}`;
      return headers;
    }
    const apiKey = getStoredApiKey();
    if (apiKey) {
      headers['X-API-Key'] = apiKey;
    }
    return headers;
  };

  const refreshAccessToken = async () => {
    if (!isAuthEnabled()) {
      return null;
    }
    if (refreshPromise) {
      return refreshPromise;
    }
    refreshPromise = (async () => {
      try {
        const refreshToken = getStoredRefreshToken();
        const response = await fetch(buildApiUrl('/auth/refresh'), {
          method: 'POST',
          credentials: 'include',
          headers: refreshToken ? { 'Content-Type': 'application/json' } : undefined,
          body: refreshToken ? JSON.stringify({ refresh_token: refreshToken }) : undefined
        });
        if (!response.ok) {
          setStoredAccessToken('', null);
          return null;
        }
        const data = await response.json();
        const token = data?.access_token || data?.token;
        const nextRefreshToken = data?.refresh_token;
        const user = data?.user || null;
        if (token) {
          setStoredAccessToken(token, user);
          if (nextRefreshToken) {
            setStoredRefreshToken(nextRefreshToken);
          }
          return token;
        }
        setStoredAccessToken('', null);
        return null;
      } catch (error) {
        return null;
      } finally {
        refreshPromise = null;
      }
    })();
    return refreshPromise;
  };

  const apiFetch = async (url, options = {}, { retryOnUnauthorized = true, includeAuth = true } = {}) => {
    const { headers: extraHeaders, ...rest } = options;
    const headers = includeAuth ? buildAuthHeaders(extraHeaders) : { ...(extraHeaders || {}) };
    const accessToken = getStoredAccessToken();
    const apiKey = getStoredApiKey();
    const shouldIncludeCredentials = isAuthEnabled();
    if (isMixedContentUrl(url)) {
      throw new Error(formatNetworkError(url));
    }
    let response;
    try {
      response = await fetch(url, {
        ...rest,
        headers,
        credentials: shouldIncludeCredentials ? 'include' : rest.credentials
      });
    } catch (error) {
      throw new Error(formatNetworkError(url));
    }
    if (
      response.status === 401 &&
      retryOnUnauthorized &&
      isAuthEnabled() &&
      (accessToken || !apiKey)
    ) {
      const refreshed = await refreshAccessToken();
      if (refreshed) {
        return apiFetch(url, options, { retryOnUnauthorized: false, includeAuth });
      }
    }
    return response;
  };

  const setAuthError = (message) => {
    lastAuthError = message ? String(message) : '';
    if (elements.authError) {
      elements.authError.textContent = lastAuthError;
      elements.authError.classList.toggle('hidden', !lastAuthError);
    }
    updateAuthDiagnostics();
  };

  const parseAuthError = async (response) => {
    let message = `http_error (${response.status})`;
    let hasDetail = false;
    try {
      const data = await response.json();
      const detail = data?.message || data?.detail;
      const errorCode = data?.error;
      if (detail || errorCode) {
        const suffix = detail || errorCode;
        message = `http_error (${response.status}): ${suffix}`;
        hasDetail = true;
      }
    } catch (error) {
      // Ignore parse errors.
    }
    if (response.status === 401 && !hasDetail) {
      message = `http_error (${response.status}): Invalid credentials.`;
    }
    return message;
  };

  const handleAuthResponse = async (response, successMessage) => {
    if (!response.ok) {
      const message = await parseAuthError(response);
      throw new Error(message);
    }
    const data = await response.json();
    const token = data?.access_token || data?.token;
    const refreshToken = data?.refresh_token;
    if (token) {
      setStoredAccessToken(token, data?.user || null);
      if (refreshToken) {
        setStoredRefreshToken(refreshToken);
      }
      if (elements.authPasswordInput) {
        elements.authPasswordInput.value = '';
      }
      setAuthError('');
      showToast(successMessage, '✅');
      refreshDashboard({ silent: true });
      return true;
    }
    throw new Error('No access token returned.');
  };

  const loginWithEmail = async () => {
    const email = elements.authEmailInput?.value.trim();
    const password = elements.authPasswordInput?.value || '';
    if (!email || !password) {
      setAuthError('Please enter your email and password.');
      return;
    }
    try {
      const response = await apiFetch(buildApiUrl('/auth/login'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      }, { includeAuth: false, retryOnUnauthorized: false });
      await handleAuthResponse(response, 'Signed in successfully.');
      loadTemplates();
    } catch (error) {
      setAuthError(error?.message || 'Unable to sign in.');
    }
  };

  const registerWithEmail = async () => {
    const email = elements.authEmailInput?.value.trim();
    const password = elements.authPasswordInput?.value || '';
    if (!email || !password) {
      setAuthError('Please enter your email and password.');
      return;
    }
    try {
      const response = await apiFetch(buildApiUrl('/auth/register'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      }, { includeAuth: false, retryOnUnauthorized: false });
      await handleAuthResponse(response, 'Registered successfully.');
      loadTemplates();
    } catch (error) {
      setAuthError(error?.message || 'Unable to register.');
    }
  };

  const logout = async () => {
    if (!isAuthEnabled()) {
      setStoredAccessToken('', null);
      return;
    }
    try {
      await apiFetch(buildApiUrl('/auth/logout'), {
        method: 'POST'
      }, { retryOnUnauthorized: false });
    } catch (error) {
      // Ignore logout failures.
    } finally {
      setStoredAccessToken('', null);
      setAuthError('');
      showToast('Signed out.', 'ℹ️');
      refreshDashboard({ silent: true });
    }
  };

  const validateAuthSession = async () => {
    if (!isAuthEnabled()) {
      return;
    }
    const token = getStoredAccessToken();
    if (!token) {
      updateAuthStatus();
      return;
    }
    try {
      let usedFallback = false;
      let response = await apiFetch(buildApiUrl('/auth/me'), {
        method: 'GET'
      }, { retryOnUnauthorized: false });
      if (response.status === 404) {
        usedFallback = true;
        response = await apiFetch(buildApiUrl('/api/templates'), {}, { retryOnUnauthorized: false });
      }
      if (response.ok) {
        if (!usedFallback && response.status !== 204) {
          const data = await response.json().catch(() => null);
          const user = data?.user || data || null;
          setStoredAccessToken(token, user);
        } else {
          updateAuthStatus();
        }
        setAuthError('');
        return;
      }
      if (response.status === 401 || response.status === 403) {
        setStoredAccessToken('', null);
        setAuthError('Session expired. Please sign in again.');
        return;
      }
      setAuthError(`Session validation failed (${response.status}).`);
    } catch (error) {
      setAuthError(error?.message || 'network_error: Unable to validate session.');
    }
  };

  const ensureAuthForAction = () => {
    if (hasAuthCredentials()) {
      return true;
    }
    showToast(missingAuthMessage, '⚠️');
    return false;
  };

  const formatShortDate = (value) => {
    if (!value) {
      return '-';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return String(value);
    }
    return date.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const renderPanelError = (element, message) => {
    if (!element) {
      return;
    }
    element.textContent = message || '';
    element.classList.toggle('hidden', !message);
  };

  const renderCount = (element, value) => {
    if (!element) {
      return;
    }
    const resolved = typeof value === 'number' && !Number.isNaN(value) ? value : 0;
    element.textContent = String(resolved);
  };

  const parseTotalCount = (data) => {
    if (!data) {
      return null;
    }
    if (typeof data.total === 'number') {
      return data.total;
    }
    if (typeof data.count === 'number') {
      return data.count;
    }
    if (Array.isArray(data)) {
      return data.length;
    }
    if (Array.isArray(data.items)) {
      return data.items.length;
    }
    if (Array.isArray(data.files)) {
      return data.files.length;
    }
    if (Array.isArray(data.artifacts)) {
      return data.artifacts.length;
    }
    return null;
  };

  const updateSummaryCounts = ({
    filesTotal = latestFilesTotal,
    artifactsTotal = latestArtifactsTotal,
    iterationsUsed = null,
    maxIterations = null,
    fallbackFiles,
    fallbackArtifacts
  } = {}) => {
    const resolvedFiles =
      typeof filesTotal === 'number' ? filesTotal : fallbackFiles ?? 0;
    const resolvedArtifacts =
      typeof artifactsTotal === 'number' ? artifactsTotal : fallbackArtifacts ?? 0;
    renderCount(elements.filesCount, resolvedFiles);
    renderCount(elements.artifactsCount, resolvedArtifacts);
    if (elements.iterationsCount) {
      const resolvedUsed = typeof iterationsUsed === 'number' && !Number.isNaN(iterationsUsed)
        ? iterationsUsed
        : typeof maxIterations === 'number'
          ? 0
          : null;
      const resolvedMax =
        typeof maxIterations === 'number' && !Number.isNaN(maxIterations) ? maxIterations : null;
      if (resolvedUsed !== null && resolvedMax !== null) {
        elements.iterationsCount.textContent = `${resolvedUsed} / ${resolvedMax}`;
      } else if (resolvedUsed !== null) {
        elements.iterationsCount.textContent = String(resolvedUsed);
      } else if (resolvedMax !== null) {
        elements.iterationsCount.textContent = `0 / ${resolvedMax}`;
      } else {
        elements.iterationsCount.textContent = '0';
      }
    }
  };

  const formatDuration = (seconds) => {
    if (typeof seconds !== 'number' || Number.isNaN(seconds) || seconds < 0) {
      return '—';
    }
    if (seconds < 1) {
      return '0s';
    }
    return `${Math.round(seconds)}s`;
  };

  const resolveIterationsUsed = (data) => {
    if (typeof data?.iterations === 'number') {
      return data.iterations;
    }
    if (typeof data?.result?.iterations === 'number') {
      return data.result.iterations;
    }
    return null;
  };

  const resolveMaxIterations = (data) => {
    if (typeof data?.max_iterations === 'number') {
      return data.max_iterations;
    }
    if (typeof data?.result?.max_iterations === 'number') {
      return data.result.max_iterations;
    }
    if (typeof data?.result?.workflow?.max_iterations === 'number') {
      return data.result.workflow.max_iterations;
    }
    return null;
  };

  const resolveFilesTotal = (data) => {
    if (typeof latestFilesTotal === 'number') {
      return latestFilesTotal;
    }
    if (typeof data?.files_count === 'number') {
      return data.files_count;
    }
    if (typeof data?.result?.files_count === 'number') {
      return data.result.files_count;
    }
    return null;
  };

  const resolveArtifactsTotal = (data) => {
    if (typeof latestArtifactsTotal === 'number') {
      return latestArtifactsTotal;
    }
    if (typeof data?.artifacts_count === 'number') {
      return data.artifacts_count;
    }
    if (typeof data?.result?.artifacts_count === 'number') {
      return data.result.artifacts_count;
    }
    return null;
  };

  const computeTimeTakenSeconds = (data) => {
    if (typeof data?.time_taken_seconds === 'number') {
      return data.time_taken_seconds;
    }
    const start = data?.created_at || data?.started_at;
    const end = data?.completed_at || data?.updated_at;
    if (!start || !end) {
      return null;
    }
    const startDate = new Date(start);
    const endDate = new Date(end);
    if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) {
      return null;
    }
    const diffSeconds = (endDate - startDate) / 1000;
    if (diffSeconds < 0) {
      return null;
    }
    return diffSeconds;
  };

  const parseResultPayload = (payload) => {
    if (typeof payload !== 'string') {
      return { value: payload, isRawString: false };
    }
    const trimmed = payload.trim();
    if (!trimmed) {
      return { value: payload, isRawString: true };
    }
    try {
      return { value: JSON.parse(payload), isRawString: false };
    } catch (error) {
      return { value: payload, isRawString: true };
    }
  };

  const renderResultJson = () => {
    if (!elements.resultJson) {
      return;
    }
    const result = latestTaskSnapshot?.result;
    if (result === undefined || result === null) {
      elements.resultJson.textContent = '';
      return;
    }
    const { value, isRawString } = parseResultPayload(result);
    if (isRawString) {
      elements.resultJson.textContent = value;
      return;
    }
    const iterations = resolveIterationsUsed(latestTaskSnapshot);
    const maxIterations = resolveMaxIterations(latestTaskSnapshot);
    const filesTotal = resolveFilesTotal(latestTaskSnapshot);
    const artifactsTotal = resolveArtifactsTotal(latestTaskSnapshot);
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const resolved = { ...value };
      if (typeof iterations === 'number') {
        resolved.iterations = iterations;
      }
      if (typeof maxIterations === 'number') {
        resolved.max_iterations = maxIterations;
      }
      if (typeof filesTotal === 'number') {
        resolved.files_count = filesTotal;
      }
      if (typeof artifactsTotal === 'number') {
        resolved.artifacts_count = artifactsTotal;
      }
      elements.resultJson.textContent = JSON.stringify(resolved, null, 2);
      return;
    }
    elements.resultJson.textContent = JSON.stringify(value, null, 2);
  };

  const refreshMetricsDisplay = () => {
    if (!latestTaskSnapshot) {
      return;
    }
    updateSummaryCounts({
      filesTotal: resolveFilesTotal(latestTaskSnapshot),
      artifactsTotal: resolveArtifactsTotal(latestTaskSnapshot),
      iterationsUsed: resolveIterationsUsed(latestTaskSnapshot),
      maxIterations: resolveMaxIterations(latestTaskSnapshot)
    });
    renderResultJson();
  };

  const updateTimeTakenDisplay = (data) => {
    if (!elements.timeTaken) {
      return;
    }
    const seconds = computeTimeTakenSeconds(data);
    if (seconds === null) {
      elements.timeTaken.textContent = '—';
      return;
    }
    elements.timeTaken.textContent = formatDuration(seconds);
  };

  const ensureGitExportButton = () => {
    if (!elements.downloadZipBtn || elements.downloadGitExportBtn) {
      return;
    }
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'primary-btn download-zip-btn';
    button.id = 'downloadGitExportBtn';
    button.textContent = 'Download Git Export';
    button.disabled = elements.downloadZipBtn.disabled;
    elements.downloadZipBtn.insertAdjacentElement('afterend', button);
    elements.downloadGitExportBtn = button;
  };

  const setDownloadEnabled = (isEnabled) => {
    if (elements.downloadZipBtn) {
      elements.downloadZipBtn.disabled = !isEnabled;
    }
    if (elements.downloadGitExportBtn) {
      elements.downloadGitExportBtn.disabled = !isEnabled;
    }
  };

  const setCreatePrEnabled = (isEnabled) => {
    if (elements.createPrBtn) {
      elements.createPrBtn.disabled = !isEnabled;
    }
  };

  const canCreatePr = () => {
    if (!latestTaskSnapshot) {
      return false;
    }
    const status = String(latestTaskSnapshot.status || '').toLowerCase();
    if (status !== 'completed') {
      return false;
    }
    const projectId = latestTaskSnapshot.project_id;
    if (!projectId) {
      return false;
    }
    const project = projectLookup.get(projectId);
    return Boolean(project?.repo_full_name);
  };

  const updateCreatePrState = () => {
    setCreatePrEnabled(canCreatePr());
  };

  const saveApiKey = () => {
    if (!elements.apiKeyInput) {
      return;
    }
    const value = elements.apiKeyInput.value || '';
    if (!value.trim()) {
      setStoredApiKey('');
      showToast('API key cleared.', 'ℹ️');
      return;
    }
    setStoredApiKey(value);
    showToast('API key saved.', '✅');
    loadTemplates();
  };

  const saveAccessToken = () => {
    if (!elements.accessTokenInput) {
      return;
    }
    const value = elements.accessTokenInput.value || '';
    if (!value.trim()) {
      setStoredAccessToken('');
      showToast('Access token cleared.', 'ℹ️');
      return;
    }
    setStoredAccessToken(value);
    showToast('Access token stored.', '✅');
    loadTemplates();
  };

  const formatProgress = (progress) => {
    if (typeof progress !== 'number' || Number.isNaN(progress)) {
      return { value: 0, percent: 0 };
    }
    const normalized = progress > 1 ? progress / 100 : progress;
    const clamped = Math.max(0, Math.min(1, normalized));
    return { value: clamped, percent: Math.round(clamped * 100) };
  };

  const normalizeTaskSnapshot = (data) => {
    if (!data || typeof data !== 'object') {
      return data;
    }
    const normalized = { ...data };
    const status = String(normalized.status || '').toLowerCase();
    if (TERMINAL_STATUSES.has(status)) {
      if (typeof normalized.progress !== 'number' || Number.isNaN(normalized.progress) || normalized.progress < 1) {
        normalized.progress = 1;
      }
    }
    if (status === 'failed') {
      if (!normalized.current_stage || normalized.current_stage === 'completed') {
        normalized.current_stage = 'review';
      }
    }
    return normalized;
  };

  const parseBoolean = (value) => {
    if (typeof value === 'boolean') {
      return value;
    }
    if (typeof value === 'number') {
      return value === 1;
    }
    if (typeof value !== 'string') {
      return false;
    }
    return ['1', 'true', 'yes', 'on'].includes(value.trim().toLowerCase());
  };

  const resolveInteractiveResearchEnabled = (taskData) => {
    if (typeof taskData?.interactive_research_enabled === 'boolean') {
      return taskData.interactive_research_enabled;
    }
    const configValue = window.__APP_CONFIG__?.ORCH_INTERACTIVE_RESEARCH;
    if (parseBoolean(configValue)) {
      return true;
    }
    const metaValue = document.querySelector('meta[name="orch-interactive-research"]')?.content;
    return parseBoolean(metaValue);
  };

  const resolveResearchChatEntries = (taskData) => {
    if (!taskData) {
      return [];
    }
    if (Array.isArray(taskData.research_chat)) {
      return taskData.research_chat;
    }
    if (Array.isArray(taskData?.artifacts?.research_chat)) {
      return taskData.artifacts.research_chat;
    }
    return [];
  };

  const resolveIntakeCanStart = (taskData) => {
    if (!taskData) {
      return false;
    }
    if (typeof taskData.can_start === 'boolean') {
      return taskData.can_start;
    }
    const normalizedStatus = String(taskData.status || '').toLowerCase();
    return ['intake_complete', 'ready_to_start'].includes(normalizedStatus);
  };

  const updateIntakeVisibility = (interactiveEnabled) => {
    if (elements.intakeChatPanel) {
      elements.intakeChatPanel.classList.toggle('hidden', !interactiveEnabled);
    }
    if (elements.legacyPromptGroup) {
      elements.legacyPromptGroup.classList.toggle('hidden', interactiveEnabled);
    }
    if (elements.interactiveDisabledHint) {
      elements.interactiveDisabledHint.classList.toggle('hidden', interactiveEnabled);
    }
  };

  const updateIntakeStatusLabel = (status) => {
    if (!elements.intakeChatStatus) {
      return;
    }
    const normalizedStatus = String(status || '').toLowerCase();
    const label =
      normalizedStatus === 'intake_complete'
        ? 'Intake: complete'
        : normalizedStatus === 'awaiting_user'
          ? 'Intake: waiting'
          : normalizedStatus
            ? `Intake: ${normalizedStatus}`
            : 'Intake: waiting';
    elements.intakeChatStatus.textContent = label;
  };

  const updateIntakeChatHint = (taskData) => {
    if (!elements.intakeChatHint) {
      return;
    }
    const normalizedStatus = String(taskData?.status || '').toLowerCase();
    if (!currentTaskId) {
      elements.intakeChatHint.textContent = 'Опишите задачу. Я задам 3 уточняющих вопроса…';
      return;
    }
    if (normalizedStatus === 'intake_complete') {
      elements.intakeChatHint.textContent = 'Intake complete. You can start AI processing.';
      return;
    }
    elements.intakeChatHint.textContent = 'Ответьте на вопросы, чтобы завершить intake.';
  };

  const renderIntakeChat = (messages) => {
    if (!elements.intakeChatHistory) {
      return;
    }
    if (!Array.isArray(messages) || !messages.length) {
      elements.intakeChatHistory.innerHTML =
        `<div class="task-lookup-hint">${intakeChatEmptyMessage}</div>`;
      return;
    }
    elements.intakeChatHistory.innerHTML = messages
      .map((entry) => {
        const role = entry?.role || 'assistant';
        const content = entry?.content || '';
        const roundLabel = entry?.round ? `Round ${entry.round}` : '';
        const roleLabel = role === 'user' ? 'You' : 'Assistant';
        return `
          <div class="chat-message ${role}">
            <div class="chat-meta">${roleLabel} ${roundLabel}</div>
            <div class="chat-content">${content}</div>
          </div>
        `;
      })
      .join('');
    elements.intakeChatHistory.scrollTop = elements.intakeChatHistory.scrollHeight;
  };

  const updateStartProcessingState = ({ canStart, interactiveEnabled } = {}) => {
    const canStartValue = typeof canStart === 'boolean' ? canStart : intakeCanStart;
    const interactiveValue =
      typeof interactiveEnabled === 'boolean' ? interactiveEnabled : resolveInteractiveResearchEnabled(latestTaskSnapshot);
    if (elements.submitTaskBtn) {
      elements.submitTaskBtn.disabled = interactiveValue ? !canStartValue : false;
    }
  };

  const resolveLastMessageByRole = (messages, role) => {
    if (!Array.isArray(messages)) {
      return null;
    }
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const entry = messages[index];
      if (entry?.role === role && entry?.content) {
        return entry.content;
      }
    }
    return null;
  };

  const updateResearchChatHint = (normalizedStatus) => {
    if (!elements.researchChatHint) {
      return;
    }
    if (!normalizedStatus) {
      elements.researchChatHint.textContent =
        'Please answer the assistant questions below to continue the task.';
      return;
    }
    const isAwaiting = AWAITING_USER_STATUSES.has(normalizedStatus);
    if (!isAwaiting) {
      elements.researchChatHint.textContent = 'ИИ формирует вопросы...';
    } else {
      elements.researchChatHint.textContent =
        'Please answer the assistant questions below to continue the task.';
    }
  };

  const shouldShowResearchChat = (normalizedStatus, normalizedStage, interactiveEnabled) => {
    if (RESEARCH_CHAT_STATUSES.has(normalizedStatus)) {
      return true;
    }
    if (interactiveEnabled && RESEARCH_STAGES.has(normalizedStage)) {
      return true;
    }
    return false;
  };

  const updateDebugPanel = (taskData) => {
    if (!elements.debugPanel) {
      return;
    }
    elements.debugPanel.classList.toggle('hidden', !debugEnabled);
    if (!debugEnabled) {
      return;
    }
    const messages = resolveResearchChatEntries(taskData);
    const lastAssistant = resolveLastMessageByRole(messages, 'assistant');
    const lastUser = resolveLastMessageByRole(messages, 'user');
    if (elements.debugApiBaseUrl) {
      elements.debugApiBaseUrl.textContent = runtimeConfig.apiBaseUrl || '(relative)';
    }
    if (elements.debugTaskId) {
      elements.debugTaskId.textContent = currentTaskId || '-';
    }
    if (elements.debugTaskStatus) {
      elements.debugTaskStatus.textContent = taskData?.status || '-';
    }
    if (elements.debugCanStart) {
      elements.debugCanStart.textContent = String(resolveIntakeCanStart(taskData));
    }
    if (elements.debugTaskStage) {
      elements.debugTaskStage.textContent = taskData?.current_stage || '-';
    }
    if (elements.debugResearchChatCount) {
      elements.debugResearchChatCount.textContent = Array.isArray(messages)
        ? String(messages.length)
        : '0';
    }
    if (elements.debugLastAssistant) {
      elements.debugLastAssistant.textContent = lastAssistant || '-';
    }
    if (elements.debugLastUser) {
      elements.debugLastUser.textContent = lastUser || '-';
    }
  };

  const updateStatusPanel = (data) => {
    if (!data) {
      return;
    }
    const normalized = normalizeTaskSnapshot(data);
    latestTaskSnapshot = normalized;
    const isCompleted = String(normalized.status).toLowerCase() === 'completed';
    setDownloadEnabled(isCompleted);
    updateCreatePrState();
    if (elements.taskStatus) {
      elements.taskStatus.textContent = normalized.status || '-';
    }
    if (elements.currentStage) {
      elements.currentStage.textContent = normalized.current_stage || '-';
    }
    const progressInfo = formatProgress(normalized.progress);
    if (elements.progressPercentage) {
      elements.progressPercentage.textContent = `${progressInfo.percent}%`;
    }
    if (elements.progressBarFill) {
      elements.progressBarFill.style.width = `${progressInfo.percent}%`;
    }
    if (elements.taskError) {
      elements.taskError.textContent = normalized.error || '';
      elements.taskError.classList.toggle('hidden', !normalized.error);
    }
    updateTimeTakenDisplay(normalized);
    refreshMetricsDisplay();
    const normalizedStatus = String(normalized.status).toLowerCase();
    const normalizedStage = String(normalized.current_stage || '').toLowerCase();
    const interactiveEnabled = resolveInteractiveResearchEnabled(normalized);
    const showResearchChat = shouldShowResearchChat(
      normalizedStatus,
      normalizedStage,
      interactiveEnabled
    );
    researchChatEmptyMessage = AWAITING_USER_STATUSES.has(normalizedStatus)
      ? 'No chat messages yet.'
      : 'ИИ формирует вопросы...';
    updateResearchChatHint(normalizedStatus);
    setResearchChatPanelVisible(showResearchChat);
    if (showResearchChat && currentTaskId) {
      loadResearchChat(currentTaskId);
    }
    if (normalizedStatus === 'needs_input' && currentTaskId) {
      if (normalized.awaiting_manual_step) {
        setClarificationPanelVisible(false);
        renderManualStepPanel(normalized);
        setManualStepPanelVisible(true);
      } else {
        setManualStepPanelVisible(false);
        loadClarificationQuestions(currentTaskId);
      }
    } else {
      setClarificationPanelVisible(false);
      setManualStepPanelVisible(false);
    }
    intakeChatEmptyMessage = normalizedStatus === 'awaiting_user'
      ? 'Waiting for your response...'
      : normalizedStatus === 'intake_complete'
        ? 'Intake complete.'
        : 'Напишите первое сообщение, чтобы начать.';
    intakeCanStart = resolveIntakeCanStart(normalized);
    updateIntakeStatusLabel(normalized.status);
    updateIntakeChatHint(normalized);
    renderIntakeChat(resolveResearchChatEntries(normalized));
    updateIntakeVisibility(interactiveEnabled);
    updateStartProcessingState({ canStart: intakeCanStart, interactiveEnabled });
    updateDebugPanel(normalized);
  };
  const isTerminalState = (data) => {
    const progressInfo = formatProgress(data?.progress);
    const isCompletedByProgress =
      progressInfo.value >= 1 && String(data?.current_stage).toLowerCase() === 'completed';
    return TERMINAL_STATUSES.has(String(data?.status).toLowerCase()) || isCompletedByProgress;
  };

  const resetResultPanel = () => {
    if (elements.taskError) {
      elements.taskError.textContent = '';
      elements.taskError.classList.add('hidden');
    }
    if (elements.resultJson) {
      elements.resultJson.textContent = '';
    }
    latestFilesTotal = null;
    latestArtifactsTotal = null;
    latestTaskSnapshot = null;
    latestQuestionsPayload = null;
    lastQuestionsSignature = '';
    updateSummaryCounts({ filesTotal: 0, artifactsTotal: 0, iterationsUsed: 0, maxIterations: null });
    setDownloadEnabled(false);
    setCreatePrEnabled(false);
    updateTimeTakenDisplay({});
    if (elements.taskStatus) {
      elements.taskStatus.textContent = '-';
    }
    if (elements.currentStage) {
      elements.currentStage.textContent = '-';
    }
    if (elements.progressPercentage) {
      elements.progressPercentage.textContent = '0%';
    }
    if (elements.progressBarFill) {
      elements.progressBarFill.style.width = '0%';
    }
    if (elements.resultStatus) {
      elements.resultStatus.innerHTML = '<span class="status-badge">In progress</span>';
    }
    if (elements.latestReviewResult) {
      elements.latestReviewResult.textContent = '—';
    }
    if (elements.clarificationForm) {
      elements.clarificationForm.innerHTML = '';
    }
    setClarificationPanelVisible(false);
    setResearchChatPanelVisible(false);
    setManualStepPanelVisible(false);
    if (elements.manualStepStage) {
      elements.manualStepStage.textContent = '-';
    }
    if (elements.manualStepReviewStatus) {
      elements.manualStepReviewStatus.textContent = '-';
    }
    if (elements.manualStepPreview) {
      elements.manualStepPreview.textContent = '-';
    }
    if (elements.researchChatHistory) {
      elements.researchChatHistory.innerHTML = '';
    }
    if (elements.researchChatInput) {
      elements.researchChatInput.value = '';
    }
    researchChatEmptyMessage = 'No chat messages yet.';
    updateResearchChatHint('');
    if (elements.intakeChatHistory) {
      elements.intakeChatHistory.innerHTML = '';
    }
    if (elements.intakeChatInput) {
      elements.intakeChatInput.value = '';
    }
    intakeChatEmptyMessage = 'Напишите первое сообщение, чтобы начать.';
    updateIntakeStatusLabel('');
    updateIntakeChatHint(null);
    updateStartProcessingState({ canStart: false, interactiveEnabled: resolveInteractiveResearchEnabled(null) });
    updateDebugPanel(null);
    resetFilePanel();
  };

  const stopPolling = () => {
    Object.keys(pollingIntervals).forEach((key) => {
      if (pollingIntervals[key]) {
        clearInterval(pollingIntervals[key]);
        pollingIntervals[key] = null;
      }
    });
    pollStartTime = null;
  };

  const handleTerminalState = (data) => {
    if (!elements.resultStatus) {
      return;
    }
    if (data.status === 'completed') {
      elements.resultStatus.innerHTML = '<span class="status-badge success">✓ Completed</span>';
    } else if (data.status === 'failed') {
      elements.resultStatus.innerHTML = '<span class="status-badge error">✕ Failed</span>';
    } else {
      elements.resultStatus.innerHTML = '<span class="status-badge error">⚠️ Error</span>';
    }
  };

  const schedulePoll = (taskId) => {
    pollingIntervals.status = setInterval(() => pollTask(taskId), POLL_INTERVAL_MS);
    pollingIntervals.state = setInterval(() => pollState(taskId), POLL_INTERVAL_MS);
    pollingIntervals.events = setInterval(() => pollEvents(taskId), POLL_SLOW_INTERVAL_MS);
    pollingIntervals.artifacts = setInterval(() => pollArtifacts(taskId), POLL_SLOW_INTERVAL_MS);
    pollingIntervals.files = setInterval(() => pollFiles(taskId), POLL_SLOW_INTERVAL_MS);
  };

  const fetchJson = async (url) => {
    try {
      const response = await apiFetch(url);
      if (!response.ok) {
        const message = response.status === 401 || response.status === 403
          ? 'Invalid credentials or no access to this task.'
          : response.status === 501
            ? 'DB not enabled on backend'
            : response.status === 404
              ? 'Task not found'
              : `Request failed (${response.status})`;
        return { error: message, status: response.status };
      }
      const data = await response.json();
      return { data };
    } catch (error) {
      return { error: 'Unable to reach the backend. Please try again.' };
    }
  };

  const fetchTask = async (taskId) => fetchJson(buildApiUrl(`/api/tasks/${taskId}`));

  const fetchFiles = async (
    taskId,
    { limit = 1, order = 'desc' } = {}
  ) => {
    const params = new URLSearchParams({ limit: String(limit), order });
    return fetchJson(buildApiUrl(`/api/tasks/${taskId}/files?${params.toString()}`));
  };

  const fetchState = async (taskId) =>
    fetchJson(buildApiUrl(`/api/tasks/${taskId}/state`));

  const fetchEvents = async (taskId, { limit = 200, order = 'desc' } = {}) => {
    const params = new URLSearchParams({ limit: String(limit), order });
    return fetchJson(buildApiUrl(`/api/tasks/${taskId}/events?${params.toString()}`));
  };

  const fetchArtifacts = async (
    taskId,
    { type = '', limit = 200, order = 'desc' } = {}
  ) => {
    const params = new URLSearchParams({ limit: String(limit), order });
    if (type) {
      params.set('type', type);
    }
    return fetchJson(buildApiUrl(`/api/tasks/${taskId}/artifacts?${params.toString()}`));
  };

  const fetchQuestions = async (taskId) =>
    fetchJson(buildApiUrl(`/api/tasks/${taskId}/questions`));

  const formatPayloadSummary = (payload) => {
    if (payload === null || payload === undefined) {
      return 'No payload';
    }
    const text = typeof payload === 'string' ? payload : JSON.stringify(payload);
    if (!text) {
      return 'No payload';
    }
    return text.length > 120 ? `${text.slice(0, 120)}…` : text;
  };

  const formatArtifactSummary = (artifact) => {
    const payload = artifact?.payload ?? artifact?.data ?? artifact;
    if (artifact?.type === 'review_report' && payload && typeof payload === 'object') {
      const passed =
        payload?.passed === true ? 'passed' : payload?.passed === false ? 'failed' : 'unknown';
      const ruffExit =
        payload?.ruff?.exit_code === null || payload?.ruff?.exit_code === undefined
          ? 'n/a'
          : payload.ruff.exit_code;
      const pytestExit =
        payload?.pytest?.exit_code === null || payload?.pytest?.exit_code === undefined
          ? 'n/a'
          : payload.pytest.exit_code;
      return `Review ${passed} (ruff: ${ruffExit}, pytest: ${pytestExit})`;
    }
    if (artifact?.type === 'patch_diff' && payload && typeof payload === 'object') {
      const total = payload?.stats?.changed_total ?? 0;
      const textFiles = payload?.stats?.text_files ?? 0;
      const binaryFiles = payload?.stats?.binary_files ?? 0;
      return `Patch diff: ${total} changed (${textFiles} text, ${binaryFiles} binary)`;
    }
    if (artifact?.type === 'repro_manifest' && payload && typeof payload === 'object') {
      const python = payload?.python_version?.split(' ')[0] || 'python';
      const review = payload?.review_summary?.passed;
      const reviewLabel =
        review === true ? 'review passed' : review === false ? 'review failed' : 'review n/a';
      return `Repro manifest: ${python}, ${reviewLabel}`;
    }
    return formatPayloadSummary(payload);
  };

  const getItemKey = (item) =>
    item?.id || item?._id || item?.event_id || item?.artifact_id || item?.created_at || '';

  const getArtifactKey = (artifact) => {
    const id = artifact?.id || artifact?._id || artifact?.artifact_id;
    if (id) {
      return `id:${id}`;
    }
    const type = artifact?.type || '';
    const producedBy = artifact?.produced_by || '';
    const createdAt = artifact?.created_at || '';
    return `meta:${type}|${producedBy}|${createdAt}`;
  };

  const dedupeArtifacts = (artifacts) => {
    if (!Array.isArray(artifacts)) {
      return [];
    }
    const seen = new Set();
    return artifacts.filter((artifact, index) => {
      const baseKey = getArtifactKey(artifact);
      const key = baseKey || JSON.stringify(artifact) || `index:${index}`;
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });
  };

  const normalizeStatePayload = (payload) => {
    if (!payload) {
      return { state: null, updatedAt: null };
    }
    if (payload.state) {
      return { state: payload.state, updatedAt: payload.updated_at };
    }
    return { state: payload, updatedAt: payload.updated_at };
  };

  const resolveStateValue = (value) =>
    value === null || value === undefined || value === '' ? '-' : value;

  const renderStatePanel = (payload) => {
    if (!elements.stateTable) {
      return;
    }
    const { state, updatedAt } = normalizeStatePayload(payload);
    const resolvedUpdatedAt =
      updatedAt || state?.timestamps?.updated_at || state?.timestamps?.updatedAt;
    const entries = [
      { label: 'status', value: state?.status },
      { label: 'progress', value: state?.progress },
      { label: 'current_stage', value: state?.current_stage },
      { label: 'active_role', value: state?.active_role },
      { label: 'current_task', value: state?.current_task },
      { label: 'container_state', value: state?.container_state },
      { label: 'container_progress', value: state?.container_progress },
      { label: 'updated_at', value: formatShortDate(resolvedUpdatedAt) }
    ];
    elements.stateTable.innerHTML = entries
      .map(
        (entry) => `
          <div class="state-item">
            <span>${entry.label}</span>
            <strong>${resolveStateValue(entry.value)}</strong>
          </div>
        `
      )
      .join('');
  };

  const setClarificationPanelVisible = (isVisible) => {
    if (!elements.clarificationPanel) {
      return;
    }
    elements.clarificationPanel.classList.toggle('hidden', !isVisible);
  };

  const setResearchChatPanelVisible = (isVisible) => {
    if (!elements.researchChatPanel) {
      return;
    }
    elements.researchChatPanel.classList.toggle('hidden', !isVisible);
  };

  const setManualStepPanelVisible = (isVisible) => {
    if (!elements.manualStepPanel) {
      return;
    }
    elements.manualStepPanel.classList.toggle('hidden', !isVisible);
  };

  const buildQuestionInput = (question, answerValue) => {
    const questionId = question.id;
    const labelText = question.required ? `${question.text} *` : question.text;
    const rationale = question.rationale ? `<div class="task-lookup-hint">${question.rationale}</div>` : '';
    if (question.type === 'choice' && Array.isArray(question.choices)) {
      const options = question.choices
        .map((choice) => {
          const selected = choice === answerValue ? 'selected' : '';
          return `<option value="${choice}" ${selected}>${choice}</option>`;
        })
        .join('');
      return `
        <div class="form-group">
          <label>${labelText}</label>
          <select class="task-priority-select" data-question-id="${questionId}">
            <option value="">Select...</option>
            ${options}
          </select>
          ${rationale}
        </div>
      `;
    }
    if (question.type === 'multi' && Array.isArray(question.choices)) {
      const selectedValues = Array.isArray(answerValue) ? answerValue : [];
      const options = question.choices
        .map((choice) => {
          const checked = selectedValues.includes(choice) ? 'checked' : '';
          return `
            <label class="task-lookup-hint">
              <input type="checkbox" data-question-id="${questionId}" value="${choice}" ${checked} />
              ${choice}
            </label>
          `;
        })
        .join('');
      return `
        <div class="form-group">
          <label>${labelText}</label>
          <div>${options}</div>
          ${rationale}
        </div>
      `;
    }
    const safeValue = answerValue ? String(answerValue) : '';
    return `
      <div class="form-group">
        <label>${labelText}</label>
        <textarea
          class="task-description-input"
          rows="3"
          data-question-id="${questionId}"
        >${safeValue}</textarea>
        ${rationale}
      </div>
    `;
  };

  const renderClarificationPanel = (payload) => {
    if (!elements.clarificationForm || !elements.clarificationMessage) {
      return;
    }
    latestQuestionsPayload = payload;
    const questions = Array.isArray(payload?.pending_questions) ? payload.pending_questions : [];
    if (!questions.length) {
      elements.clarificationForm.innerHTML = '<div class="task-lookup-hint">No clarification questions available.</div>';
      return;
    }
    const providedAnswers = payload?.provided_answers || {};
    elements.clarificationForm.innerHTML = questions
      .map((question) => buildQuestionInput(question, providedAnswers[question.id]))
      .join('');
    const requestedAt = payload?.requested_at ? `Requested at: ${formatShortDate(payload.requested_at)}` : '';
    elements.clarificationMessage.textContent = requestedAt
      ? `Please answer the questions below. ${requestedAt}`
      : 'Please answer the questions below so the task can continue.';
  };

  const renderResearchChat = (artifacts) => {
    if (!elements.researchChatHistory) {
      return;
    }
    if (!Array.isArray(artifacts) || !artifacts.length) {
      elements.researchChatHistory.innerHTML =
        `<div class="task-lookup-hint">${researchChatEmptyMessage}</div>`;
      return;
    }
    elements.researchChatHistory.innerHTML = artifacts
      .map((artifact) => {
        const payload = artifact?.payload || {};
        const role = payload.role || 'assistant';
        const content = payload.content || '';
        const roundLabel = payload.round ? `Round ${payload.round}` : '';
        const roleLabel = role === 'user' ? 'You' : 'Assistant';
        return `
          <div class="chat-message ${role}">
            <div class="chat-meta">${roleLabel} ${roundLabel}</div>
            <div class="chat-content">${content}</div>
          </div>
        `;
      })
      .join('');
    elements.researchChatHistory.scrollTop = elements.researchChatHistory.scrollHeight;
  };

  const loadResearchChat = async (taskId) => {
    if (!taskId) {
      return;
    }
    const { data, error } = await fetchArtifacts(taskId, { type: 'research_chat', limit: 200, order: 'asc' });
    if (error) {
      return;
    }
    const artifacts = Array.isArray(data) ? data : data?.artifacts || data?.items || [];
    const signature = JSON.stringify(artifacts.map(getArtifactKey));
    if (signature === lastResearchChatSignature) {
      return;
    }
    lastResearchChatSignature = signature;
    renderResearchChat(artifacts);
  };

  const renderManualStepPanel = (payload) => {
    if (!elements.manualStepPanel) {
      return;
    }
    if (elements.manualStepStage) {
      elements.manualStepStage.textContent = payload?.manual_step_stage || '-';
    }
    if (elements.manualStepReviewStatus) {
      elements.manualStepReviewStatus.textContent = payload?.last_review_status || '-';
    }
    if (elements.manualStepPreview) {
      const preview = payload?.next_task_preview;
      elements.manualStepPreview.textContent = preview
        ? JSON.stringify(preview, null, 2)
        : '-';
    }
    if (elements.manualStepMessage) {
      elements.manualStepMessage.textContent = payload?.manual_step_stage
        ? `Awaiting manual action at ${payload.manual_step_stage}.`
        : 'The task is awaiting a manual next step decision.';
    }
  };

  const collectClarificationAnswers = () => {
    if (!elements.clarificationForm || !latestQuestionsPayload) {
      return {};
    }
    const questions = Array.isArray(latestQuestionsPayload.pending_questions)
      ? latestQuestionsPayload.pending_questions
      : [];
    const answers = {};
    questions.forEach((question) => {
      if (!question?.id) {
        return;
      }
      if (question.type === 'multi') {
        const checked = [
          ...elements.clarificationForm.querySelectorAll(`input[data-question-id="${question.id}"]:checked`)
        ].map((item) => item.value);
        if (checked.length) {
          answers[question.id] = checked;
        }
        return;
      }
      const field = elements.clarificationForm.querySelector(`[data-question-id="${question.id}"]`);
      if (!field) {
        return;
      }
      const value = field.value?.trim() || '';
      if (value) {
        answers[question.id] = value;
      }
    });
    return answers;
  };

  const resetFilePanel = () => {
    activeFileCategory = 'all';
    activeFilePath = '';
    activeFileContent = '';
    latestFilesSnapshot = null;
    if (elements.fileCategories) {
      elements.fileCategories.innerHTML =
        '<div class="category-item active" data-category="all">All Files</div>';
    }
    if (elements.fileList) {
      elements.fileList.innerHTML = '<div class="file-item">No files yet.</div>';
    }
    if (elements.previewFileName) {
      elements.previewFileName.textContent = 'Select a file to preview';
    }
    if (elements.fileContentPreview) {
      elements.fileContentPreview.textContent = '// Select a file to view its content';
    }
    if (elements.copyFileBtn) {
      elements.copyFileBtn.disabled = true;
    }
  };

  const formatFileLabel = (path) => {
    if (!path) {
      return 'Untitled';
    }
    const segments = path.split('/');
    return segments[segments.length - 1] || path;
  };

  const renderFileCategories = (filesData) => {
    if (!elements.fileCategories) {
      return;
    }
    const byType = filesData?.by_type || {};
    const categories = [
      { key: 'all', label: `All Files (${filesData?.total ?? 0})` },
      { key: 'code', label: `Code (${byType.code?.length ?? 0})` },
      { key: 'config', label: `Config (${byType.config?.length ?? 0})` },
      { key: 'docs', label: `Docs (${byType.docs?.length ?? 0})` },
      { key: 'tests', label: `Tests (${byType.tests?.length ?? 0})` },
      { key: 'other', label: `Other (${byType.other?.length ?? 0})` }
    ];
    elements.fileCategories.innerHTML = categories
      .map(
        (category) => `
          <div class="category-item ${category.key === activeFileCategory ? 'active' : ''}" data-category="${category.key}">
            ${category.label}
          </div>
        `
      )
      .join('');
  };

  const resolveFilesForCategory = (filesData, category) => {
    if (!filesData) {
      return [];
    }
    if (category === 'all') {
      return filesData.all_files || [];
    }
    return filesData.by_type?.[category] || [];
  };

  const renderFileList = (filesData) => {
    if (!elements.fileList) {
      return;
    }
    const files = resolveFilesForCategory(filesData, activeFileCategory);
    if (!files.length) {
      elements.fileList.innerHTML = '<div class="file-item">No files in this category.</div>';
      return;
    }
    elements.fileList.innerHTML = files
      .map((path) => {
        const isActive = path === activeFilePath;
        return `
          <div class="file-item ${isActive ? 'active' : ''}" data-path="${path}">
            <span class="file-icon">📄</span>
            <span class="file-name">${formatFileLabel(path)}</span>
          </div>
        `;
      })
      .join('');
  };

  const encodeFilePath = (path) =>
    encodeURIComponent(path).replace(/%2F/g, '/');

  const fetchFileContent = async (taskId, filepath) =>
    fetchJson(buildApiUrl(`/api/tasks/${taskId}/files/${encodeFilePath(filepath)}`));

  const renderFilePreview = (filename, content) => {
    if (elements.previewFileName) {
      elements.previewFileName.textContent = filename || 'Select a file to preview';
    }
    if (elements.fileContentPreview) {
      elements.fileContentPreview.textContent = content || '// No content available';
    }
    if (elements.copyFileBtn) {
      elements.copyFileBtn.disabled = !content;
    }
  };

  const handleFileSelection = async (taskId, path) => {
    if (!taskId || !path) {
      return;
    }
    activeFilePath = path;
    renderFileList(latestFilesSnapshot);
    renderFilePreview(formatFileLabel(path), 'Loading file content...');
    const { data, error } = await fetchFileContent(taskId, path);
    if (error) {
      renderFilePreview(formatFileLabel(path), `Unable to load file: ${error}`);
      return;
    }
    const content = data?.content ?? '';
    activeFileContent = content;
    renderFilePreview(formatFileLabel(path), content);
  };

  const copyFileContent = async () => {
    if (!activeFileContent) {
      showToast('No file selected to copy.', '⚠️');
      return;
    }
    try {
      await navigator.clipboard.writeText(activeFileContent);
      showToast('File content copied.', '✅');
      return;
    } catch (error) {
      const textarea = document.createElement('textarea');
      textarea.value = activeFileContent;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'absolute';
      textarea.style.left = '-9999px';
      document.body.appendChild(textarea);
      textarea.select();
      const success = document.execCommand('copy');
      document.body.removeChild(textarea);
      showToast(success ? 'File content copied.' : 'Unable to copy file content.', success ? '✅' : '⚠️');
    }
  };

  let latestFilesSnapshot = null;

  const renderEvents = (events) => {
    if (!elements.eventsList) {
      return;
    }
    if (!Array.isArray(events) || events.length === 0) {
      elements.eventsList.innerHTML = '<div class="event-item">No events yet.</div>';
      return;
    }
    elements.eventsList.innerHTML = events
      .map((event) => {
        const payload = event?.payload ?? event?.data ?? event?.details ?? event;
        return `
          <div class="event-item">
            <div class="event-header">
              <span class="event-type">${event?.type || 'event'}</span>
              <span class="event-meta">${formatShortDate(event?.created_at)}</span>
            </div>
            <details class="payload-details">
              <summary>${formatPayloadSummary(payload)}</summary>
              <pre>${JSON.stringify(payload, null, 2)}</pre>
            </details>
          </div>
        `;
      })
      .join('');
  };

  const updateLatestReviewResult = (artifacts) => {
    if (!elements.latestReviewResult) {
      return;
    }
    if (!Array.isArray(artifacts)) {
      elements.latestReviewResult.textContent = '—';
      return;
    }
    const reviewArtifact = artifacts.find((item) => item?.type === 'review_report');
    if (!reviewArtifact) {
      if (!artifactTypeFilter || artifactTypeFilter === 'review_report') {
        elements.latestReviewResult.textContent = '—';
      }
      return;
    }
    const payload = reviewArtifact?.payload ?? reviewArtifact;
    const passed = payload?.passed;
    const statusLabel =
      passed === true ? 'Passed' : passed === false ? 'Failed' : 'Unknown';
    elements.latestReviewResult.textContent = statusLabel;
  };

  const renderArtifacts = (artifacts) => {
    if (!elements.artifactsList) {
      return;
    }
    updateLatestReviewResult(artifacts);
    if (!Array.isArray(artifacts) || artifacts.length === 0) {
      elements.artifactsList.innerHTML = '<div class="artifact-item">No artifacts yet.</div>';
      return;
    }
    elements.artifactsList.innerHTML = artifacts
      .map((artifact) => {
        const payload = artifact?.payload ?? artifact?.data ?? artifact;
        return `
          <div class="artifact-item">
            <div class="artifact-header">
              <span class="artifact-badge">${artifact?.type || 'artifact'}</span>
              <span class="artifact-meta">${formatShortDate(artifact?.created_at)}</span>
            </div>
            <div class="artifact-meta">Produced by: ${artifact?.produced_by || '-'}</div>
            <details class="payload-details">
              <summary>${formatArtifactSummary(artifact)}</summary>
              <pre>${JSON.stringify(payload, null, 2)}</pre>
            </details>
          </div>
        `;
      })
      .join('');
  };

  const loadClarificationQuestions = async (taskId) => {
    if (!taskId || !elements.clarificationPanel) {
      return;
    }
    const { data, error } = await fetchQuestions(taskId);
    if (error) {
      setClarificationPanelVisible(false);
      return;
    }
    const questions = data?.pending_questions || [];
    const signature = JSON.stringify(questions) + JSON.stringify(data?.provided_answers || {});
    if (signature === lastQuestionsSignature) {
      setClarificationPanelVisible(true);
      return;
    }
    lastQuestionsSignature = signature;
    setClarificationPanelVisible(true);
    renderClarificationPanel(data);
  };

  const pollTask = async (taskId) => {
    if (!pollStartTime) {
      pollStartTime = Date.now();
    }
    if (Date.now() - pollStartTime > POLL_TIMEOUT_MS) {
      stopPolling();
      if (elements.taskError) {
        elements.taskError.textContent = 'Timed out; try refreshing status';
        elements.taskError.classList.remove('hidden');
      }
      showToast('Timed out; try refreshing status', '⚠️');
      return;
    }

    const { data, error, status } = await fetchTask(taskId);
    if (error) {
      renderPanelError(elements.stateError, error);
      renderPanelError(elements.eventsError, error);
      renderPanelError(elements.artifactsError, error);
      if (elements.taskError) {
        elements.taskError.textContent = error;
        elements.taskError.classList.remove('hidden');
      }
      showToast(error, '⚠️');
      if (status === 404) {
        stopPolling();
        setSubmitDisabled(false);
      }
      return;
    }
    if (data) {
      const normalized = normalizeTaskSnapshot(data);
      updateStatusPanel(normalized);

      const progressInfo = formatProgress(normalized.progress);
      const isCompletedByProgress =
        progressInfo.value >= 1 && String(normalized.current_stage).toLowerCase() === 'completed';
      const isTerminal = isTerminalState(normalized);

      if (isTerminal) {
        await Promise.all([pollFiles(taskId), pollArtifacts(taskId)]);
        stopPolling();
        handleTerminalState(normalized);
        showResultsWithInspector();
        setSubmitDisabled(false);
        return;
      }
    }
  };

  const pollState = async (taskId) => {
    const { data, error } = await fetchState(taskId);
    if (error) {
      renderPanelError(elements.stateError, error);
      return;
    }
    renderPanelError(elements.stateError, '');
    renderStatePanel(data);
  };

  const pollEvents = async (taskId) => {
    const { data, error } = await fetchEvents(taskId);
    if (error) {
      renderPanelError(elements.eventsError, error);
      return;
    }
    renderPanelError(elements.eventsError, '');
    const events = Array.isArray(data) ? data : data?.events || data?.items || [];
    const signature = JSON.stringify(events.slice(0, 20).map(getItemKey));
    if (signature === lastEventSignature) {
      return;
    }
    lastEventSignature = signature;
    renderEvents(events);
  };

  const pollArtifacts = async (taskId) => {
    const { data, error } = await fetchArtifacts(taskId, { type: artifactTypeFilter });
    if (error) {
      renderPanelError(elements.artifactsError, error);
      return;
    }
    renderPanelError(elements.artifactsError, '');
    const artifacts = Array.isArray(data) ? data : data?.artifacts || data?.items || [];
    const dedupedArtifacts = dedupeArtifacts(artifacts);
    latestArtifactsTotal = dedupedArtifacts.length;
    refreshMetricsDisplay();
    const signature = JSON.stringify(dedupedArtifacts.slice(0, 20).map(getArtifactKey));
    if (signature === lastArtifactSignature) {
      return;
    }
    lastArtifactSignature = signature;
    renderArtifacts(dedupedArtifacts);
  };

  const pollFiles = async (taskId) => {
    const { data, error } = await fetchFiles(taskId);
    if (error) {
      return;
    }
    latestFilesSnapshot = data;
    const availableFiles = data?.all_files || [];
    if (activeFilePath && !availableFiles.includes(activeFilePath)) {
      activeFilePath = '';
      activeFileContent = '';
      renderFilePreview('Select a file to preview', '// Select a file to view its content');
    }
    const total = parseTotalCount(data);
    if (typeof total === 'number') {
      latestFilesTotal = total;
      refreshMetricsDisplay();
    }
    renderFileCategories(data);
    renderFileList(data);
  };

  const startPolling = (taskId) => {
    stopPolling();
    pollStartTime = Date.now();
    lastEventSignature = '';
    lastArtifactSignature = '';
    lastQuestionsSignature = '';
    lastResearchChatSignature = '';
    pollTask(taskId);
    pollState(taskId);
    pollEvents(taskId);
    pollArtifacts(taskId);
    pollFiles(taskId);
    schedulePoll(taskId);
  };

  const closeWebSocket = () => {
    if (activeSocket) {
      activeSocket.close();
      activeSocket = null;
    }
  };

  const startWebSocket = async (taskId) => {
    closeWebSocket();
    const accessToken = getStoredAccessToken();
    const apiKey = getStoredApiKey();
    let wsUrl = '';
    if (isAuthEnabled() && accessToken) {
      wsUrl = appendTokenQuery(buildWebSocketUrl(taskId), accessToken);
    } else if (apiKey) {
      wsUrl = appendApiKeyQuery(buildWebSocketUrl(taskId));
    } else {
      return;
    }
    try {
      activeSocket = new WebSocket(wsUrl);
    } catch (error) {
      activeSocket = null;
      return;
    }
    activeSocket.addEventListener('message', async (event) => {
      if (!event?.data) {
        return;
      }
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        return;
      }
      if (payload && typeof payload === 'object') {
        const normalized = normalizeTaskSnapshot(payload);
        updateStatusPanel(normalized);
        if (isTerminalState(normalized)) {
          await Promise.all([pollFiles(taskId), pollArtifacts(taskId)]);
          stopPolling();
          handleTerminalState(normalized);
          showResultsWithInspector();
          setSubmitDisabled(false);
          closeWebSocket();
        }
      }
    });
    activeSocket.addEventListener('close', () => {
      activeSocket = null;
    });
  };

  const postClarificationInput = async (taskId, answers, { autoResume = false } = {}) => {
    try {
      const response = await apiFetch(buildApiUrl(`/api/tasks/${taskId}/input`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ answers, auto_resume: autoResume })
      });
      if (!response.ok) {
        const message = response.status === 401 || response.status === 403
          ? 'Invalid credentials or no access to this task.'
          : response.status === 400
            ? 'Please answer all required questions before resuming.'
            : `Request failed (${response.status})`;
        throw new Error(message);
      }
      return { data: await response.json() };
    } catch (error) {
      return { error: error?.message || 'Unable to submit clarification answers.' };
    }
  };

  const resumeClarificationTask = async (taskId) => {
    try {
      const response = await apiFetch(buildApiUrl(`/api/tasks/${taskId}/resume`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });
      if (!response.ok) {
        const message = response.status === 401 || response.status === 403
          ? 'Invalid credentials or no access to this task.'
          : response.status === 400
            ? 'Please answer all required questions before resuming.'
            : `Request failed (${response.status})`;
        throw new Error(message);
      }
      return { data: await response.json() };
    } catch (error) {
      return { error: error?.message || 'Unable to resume task.' };
    }
  };

  const postResearchChatMessage = async (taskId, message) => {
    try {
      const response = await apiFetch(buildApiUrl(`/api/tasks/${taskId}/chat`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ message })
      });
      if (!response.ok) {
        const messageText = response.status === 401 || response.status === 403
          ? 'Invalid credentials or no access to this task.'
          : response.status === 400
            ? 'Message cannot be empty.'
            : `Request failed (${response.status})`;
        throw new Error(messageText);
      }
      return { data: await response.json() };
    } catch (error) {
      return { error: error?.message || 'Unable to send chat message.' };
    }
  };

  const applyManualStepDecision = async (taskId, decision) => {
    try {
      const response = await apiFetch(buildApiUrl(`/api/tasks/${taskId}/next`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ decision })
      });
      if (!response.ok) {
        const message = response.status === 401 || response.status === 403
          ? 'Invalid credentials or no access to this task.'
          : response.status === 409
            ? 'Task is not awaiting manual input.'
            : `Request failed (${response.status})`;
        throw new Error(message);
      }
      return { data: await response.json() };
    } catch (error) {
      return { error: error?.message || 'Unable to apply manual step.' };
    }
  };

  const buildTaskPayload = (description, { autoStart = true } = {}) => {
    const payload = { description, auto_start: autoStart };
    const codexValue = elements.codexVersion?.value?.trim();
    if (codexValue) {
      payload.codex_version = codexValue;
    }
    const templateValue = elements.templateSelect?.value?.trim();
    if (templateValue) {
      payload.template_id = templateValue;
    }
    const projectValue = elements.projectSelect?.value?.trim();
    if (projectValue) {
      payload.project_id = projectValue;
    }
    if (window.USER_ID) {
      payload.user_id = window.USER_ID;
    }
    return payload;
  };

  const createTask = async (description, { autoStart = true } = {}) => {
    const payload = buildTaskPayload(description, { autoStart });
    try {
      const response = await apiFetch(buildApiUrl('/api/tasks'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        const message = response.status === 401 || response.status === 403
          ? 'Invalid credentials or no access to this task.'
          : `Request failed (${response.status})`;
        throw new Error(message);
      }
      return { data: await response.json() };
    } catch (error) {
      return { error: error?.message || 'Unable to create task.' };
    }
  };

  const startTaskIntake = async (taskId) => {
    try {
      const response = await apiFetch(buildApiUrl(`/api/tasks/${taskId}/intake/start`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });
      if (!response.ok) {
        const message = response.status === 409
          ? 'Intake already started.'
          : response.status === 401 || response.status === 403
            ? 'Invalid credentials or no access to this task.'
            : `Request failed (${response.status})`;
        throw new Error(message);
      }
      return { data: await response.json() };
    } catch (error) {
      return { error: error?.message || 'Unable to start intake.' };
    }
  };

  const startTaskProcessing = async (taskId) => {
    try {
      const response = await apiFetch(buildApiUrl(`/api/tasks/${taskId}/start`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });
      if (!response.ok) {
        const message = response.status === 409
          ? 'Intake not complete yet.'
          : response.status === 401 || response.status === 403
            ? 'Invalid credentials or no access to this task.'
            : `Request failed (${response.status})`;
        throw new Error(message);
      }
      return { data: await response.json() };
    } catch (error) {
      return { error: error?.message || 'Unable to start processing.' };
    }
  };

  const setActiveInspectorTab = (tab) => {
    activeInspectorTab = tab;
    if (elements.inspectorTabs) {
      elements.inspectorTabs.querySelectorAll('.tab-btn').forEach((button) => {
        button.classList.toggle('active', button.dataset.tab === tab);
      });
    }
    if (elements.statePanel) {
      elements.statePanel.classList.toggle('hidden', tab !== 'state');
    }
    if (elements.eventsPanel) {
      elements.eventsPanel.classList.toggle('hidden', tab !== 'events');
    }
    if (elements.artifactsPanel) {
      elements.artifactsPanel.classList.toggle('hidden', tab !== 'artifacts');
    }
  };

  const activateTask = (taskId, { focusState = false } = {}) => {
    currentTaskId = taskId;
    if (elements.currentTaskId) {
      elements.currentTaskId.textContent = taskId;
    }
    if (elements.taskIdInput) {
      elements.taskIdInput.value = taskId;
    }
    renderPanelError(elements.stateError, '');
    renderPanelError(elements.eventsError, '');
    renderPanelError(elements.artifactsError, '');
    if (focusState) {
      setActiveInspectorTab('state');
    }
    showSection(elements.taskProgress);
    startPolling(taskId);
    void startWebSocket(taskId);
  };

  const submitTask = async () => {
    const interactiveEnabled = resolveInteractiveResearchEnabled(latestTaskSnapshot);
    if (interactiveEnabled) {
      if (!currentTaskId) {
        showToast('Complete intake before starting processing.', 'ℹ️');
        return;
      }
      if (!intakeCanStart) {
        showToast('Intake not complete yet.', '⚠️');
        return;
      }
      if (!ensureAuthForAction()) {
        return;
      }
      setSubmitDisabled(true);
      setLoading(true, 'Starting processing...', 'Launching the AI pipeline');
      const { error } = await startTaskProcessing(currentTaskId);
      setLoading(false);
      if (error) {
        setSubmitDisabled(false);
        showToast(error, '⚠️');
        return;
      }
      if (elements.progressTime) {
        elements.progressTime.textContent = 'Started: Just now';
      }
      activateTask(currentTaskId, { focusState: true });
      updateStatusPanel({ status: 'queued', current_stage: 'starting', progress: 0 });
      return;
    }

    const description = elements.taskDescription?.value.trim();
    if (!description) {
      showToast('Please enter a task description.', '⚠️');
      return;
    }
    if (!ensureAuthForAction()) {
      return;
    }

    setSubmitDisabled(true);
    resetResultPanel();
    setLoading(true, 'Creating task...', 'Submitting your request to the AI platform');

    const { data, error } = await createTask(description, { autoStart: true });
    if (error) {
      setLoading(false);
      setSubmitDisabled(false);
      if (elements.taskError) {
        elements.taskError.textContent = error;
        elements.taskError.classList.remove('hidden');
      }
      showToast(error, '⚠️');
      return;
    }

    const taskId = data?.task_id || data?.id;
    if (!taskId) {
      setLoading(false);
      setSubmitDisabled(false);
      showToast('Task ID not returned from server', '⚠️');
      return;
    }

    if (elements.progressTime) {
      elements.progressTime.textContent = 'Started: Just now';
    }
    activateTask(taskId, { focusState: true });
    updateStatusPanel({ status: 'queued', current_stage: 'starting', progress: 0 });
    setLoading(false);
  };

  const refreshStatus = () => {
    if (!currentTaskId) {
      showToast('No active task to refresh.', 'ℹ️');
      return;
    }
    pollTask(currentTaskId);
    pollState(currentTaskId);
    pollEvents(currentTaskId);
    pollArtifacts(currentTaskId);
    pollFiles(currentTaskId);
    if (latestTaskSnapshot?.status === 'needs_input' && !latestTaskSnapshot?.awaiting_manual_step) {
      loadClarificationQuestions(currentTaskId);
    }
  };

  const submitClarificationAnswers = async () => {
    if (!currentTaskId) {
      showToast('No active task to update.', 'ℹ️');
      return;
    }
    if (!ensureAuthForAction()) {
      return;
    }
    const answers = collectClarificationAnswers();
    setLoading(true, 'Saving answers...', 'Submitting clarification responses');
    const { error } = await postClarificationInput(currentTaskId, answers);
    setLoading(false);
    if (error) {
      showToast(error, '⚠️');
      return;
    }
    showToast('Answers saved.', '✅');
    await loadClarificationQuestions(currentTaskId);
  };

  const resumeClarification = async () => {
    if (!currentTaskId) {
      showToast('No active task to resume.', 'ℹ️');
      return;
    }
    if (!ensureAuthForAction()) {
      return;
    }
    const answers = collectClarificationAnswers();
    setLoading(true, 'Resuming task...', 'Submitting answers and restarting processing');
    const inputResult = await postClarificationInput(currentTaskId, answers);
    if (inputResult.error) {
      setLoading(false);
      showToast(inputResult.error, '⚠️');
      return;
    }
    const resumeResult = await resumeClarificationTask(currentTaskId);
    setLoading(false);
    if (resumeResult.error) {
      showToast(resumeResult.error, '⚠️');
      return;
    }
    showToast('Task resumed.', '✅');
    lastQuestionsSignature = '';
    setClarificationPanelVisible(false);
    startPolling(currentTaskId);
  };

  const submitResearchChatMessage = async () => {
    if (!currentTaskId || !elements.researchChatInput) {
      return;
    }
    const message = elements.researchChatInput.value.trim();
    if (!message) {
      showToast('Please enter a message.', '⚠️');
      return;
    }
    setLoading(true, 'Sending message...', 'Submitting your response');
    const { error } = await postResearchChatMessage(currentTaskId, message);
    setLoading(false);
    if (error) {
      showToast(error, '⚠️');
      return;
    }
    elements.researchChatInput.value = '';
    await loadResearchChat(currentTaskId);
    await pollTask(currentTaskId);
  };

  const submitIntakeChatMessage = async () => {
    if (!elements.intakeChatInput) {
      return;
    }
    if (!resolveInteractiveResearchEnabled(latestTaskSnapshot)) {
      showToast('Interactive research disabled.', '⚠️');
      return;
    }
    const message = elements.intakeChatInput.value.trim();
    if (!message) {
      showToast('Please enter a message.', '⚠️');
      return;
    }
    if (!ensureAuthForAction()) {
      return;
    }

    setLoading(true, 'Sending message...', 'Submitting your intake response');
    let taskId = currentTaskId;
    if (!taskId) {
      resetResultPanel();
      const createResult = await createTask(message, { autoStart: false });
      if (createResult.error) {
        setLoading(false);
        showToast(createResult.error, '⚠️');
        return;
      }
      taskId = createResult.data?.task_id || createResult.data?.id;
      if (!taskId) {
        setLoading(false);
        showToast('Task ID not returned from server', '⚠️');
        return;
      }
      currentTaskId = taskId;
      const intakeResult = await startTaskIntake(taskId);
      if (intakeResult.error) {
        setLoading(false);
        showToast(intakeResult.error, '⚠️');
        return;
      }
    } else {
      const chatResult = await postResearchChatMessage(taskId, message);
      if (chatResult.error) {
        setLoading(false);
        showToast(chatResult.error, '⚠️');
        return;
      }
    }

    elements.intakeChatInput.value = '';
    const { data } = await fetchTask(taskId);
    setLoading(false);
    if (data) {
      updateStatusPanel(data);
    }
  };

  const continueManualStep = async () => {
    if (!currentTaskId) {
      showToast('No active task to continue.', 'ℹ️');
      return;
    }
    if (!ensureAuthForAction()) {
      return;
    }
    setLoading(true, 'Applying manual step...', 'Resuming task execution');
    const { error } = await applyManualStepDecision(currentTaskId, 'continue');
    setLoading(false);
    if (error) {
      showToast(error, '⚠️');
      return;
    }
    showToast('Manual step applied.', '✅');
    setManualStepPanelVisible(false);
    refreshStatus();
  };

  const rerunReview = async () => {
    if (!currentTaskId) {
      showToast('No active task to review.', 'ℹ️');
      return;
    }
    if (!ensureAuthForAction()) {
      return;
    }
    if (elements.rerunReviewBtn) {
      elements.rerunReviewBtn.disabled = true;
    }
    setLoading(true, 'Running review...', 'Executing ruff and pytest checks');
    try {
      const response = await apiFetch(buildApiUrl(`/api/tasks/${currentTaskId}/rerun-review`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });
      if (!response.ok) {
        const message = response.status === 401 || response.status === 403
          ? 'Invalid credentials or no access to this task.'
          : response.status === 404
            ? 'Task or container not found'
            : `Review rerun failed (${response.status})`;
        throw new Error(message);
      }
      await response.json();
      showToast('Review rerun completed.', '✅');
      await pollArtifacts(currentTaskId);
      const { data } = await fetchArtifacts(currentTaskId, { type: 'review_report', limit: 5 });
      const reviewArtifacts = Array.isArray(data) ? data : data?.artifacts || data?.items || [];
      updateLatestReviewResult(dedupeArtifacts(reviewArtifacts));
    } catch (error) {
      const message = error?.message || 'Unable to rerun review.';
      showToast(message, '⚠️');
    } finally {
      setLoading(false);
      if (elements.rerunReviewBtn) {
        elements.rerunReviewBtn.disabled = false;
      }
    }
  };

  const loadTask = () => {
    const taskId = elements.taskIdInput?.value.trim();
    if (!taskId) {
      showToast('Please enter a task_id to load.', '⚠️');
      return;
    }
    if (!ensureAuthForAction()) {
      return;
    }
    resetResultPanel();
    activateTask(taskId, { focusState: true });
  };

  const copyTaskId = async () => {
    const value = elements.taskIdInput?.value || currentTaskId || '';
    if (!value) {
      showToast('No task_id to copy.', '⚠️');
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      showToast('Task ID copied.', '✅');
    } catch (error) {
      showToast('Unable to copy task ID.', '⚠️');
    }
  };

  if (elements.startTaskBtn) {
    elements.startTaskBtn.addEventListener('click', () => {
      showSection(elements.taskCreation);
    });
  }

  if (elements.startFirstTaskBtn) {
    elements.startFirstTaskBtn.addEventListener('click', () => {
      showSection(elements.taskCreation);
    });
  }

  if (elements.newTaskFromResultsBtn) {
    elements.newTaskFromResultsBtn.addEventListener('click', () => {
      showSection(elements.taskCreation);
    });
  }

  if (elements.backToMainBtn) {
    elements.backToMainBtn.addEventListener('click', () => {
      showSection(elements.welcomeScreen);
    });
  }

  if (elements.cancelTaskBtn) {
    elements.cancelTaskBtn.addEventListener('click', () => {
      showSection(elements.welcomeScreen);
    });
  }

  if (elements.viewTasksBtn) {
    elements.viewTasksBtn.addEventListener('click', () => {
      showSection(elements.previousTasks);
      refreshDashboard();
    });
  }

  if (elements.refreshDashboardBtn) {
    elements.refreshDashboardBtn.addEventListener('click', refreshDashboard);
  }

  if (elements.createProjectBtn) {
    elements.createProjectBtn.addEventListener('click', createProject);
  }

  if (elements.connectGithubBtn) {
    elements.connectGithubBtn.addEventListener('click', connectGithubProject);
  }

  if (elements.testGithubBtn) {
    elements.testGithubBtn.addEventListener('click', testGithubConnection);
  }

  if (elements.refreshProgressBtn) {
    elements.refreshProgressBtn.addEventListener('click', refreshStatus);
  }

  if (elements.submitClarificationBtn) {
    elements.submitClarificationBtn.addEventListener('click', submitClarificationAnswers);
  }

  if (elements.resumeTaskBtn) {
    elements.resumeTaskBtn.addEventListener('click', resumeClarification);
  }

  if (elements.researchChatSendBtn) {
    elements.researchChatSendBtn.addEventListener('click', submitResearchChatMessage);
  }

  if (elements.intakeChatSendBtn) {
    elements.intakeChatSendBtn.addEventListener('click', submitIntakeChatMessage);
  }

  if (elements.nextStepBtn) {
    elements.nextStepBtn.addEventListener('click', continueManualStep);
  }

  if (elements.submitTaskBtn) {
    elements.submitTaskBtn.addEventListener('click', submitTask);
  }

  if (elements.projectSelect) {
    elements.projectSelect.addEventListener('change', applyProjectTemplate);
  }

  if (elements.saveApiKeyBtn) {
    elements.saveApiKeyBtn.addEventListener('click', saveApiKey);
  }
  if (elements.saveAccessTokenBtn) {
    elements.saveAccessTokenBtn.addEventListener('click', saveAccessToken);
  }
  if (elements.googleSignInBtn) {
    elements.googleSignInBtn.addEventListener('click', () => {
      const returnTo = `${window.location.origin}${window.location.pathname}`;
      const loginUrl = buildApiUrl(`/auth/google/login?return_to=${encodeURIComponent(returnTo)}`);
      window.location.assign(loginUrl);
    });
  }

  if (elements.authLoginBtn) {
    elements.authLoginBtn.addEventListener('click', loginWithEmail);
  }

  if (elements.authRegisterBtn) {
    elements.authRegisterBtn.addEventListener('click', registerWithEmail);
  }

  if (elements.authLogoutBtn) {
    elements.authLogoutBtn.addEventListener('click', logout);
  }

  if (elements.apiKeyInput) {
    elements.apiKeyInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        saveApiKey();
      }
    });
  }
  if (elements.accessTokenInput) {
    elements.accessTokenInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        saveAccessToken();
      }
    });
  }

  const handleAuthInputSubmit = (event, action) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      action();
    }
  };

  if (elements.authEmailInput) {
    elements.authEmailInput.addEventListener('keydown', (event) => {
      handleAuthInputSubmit(event, loginWithEmail);
    });
  }

  if (elements.authPasswordInput) {
    elements.authPasswordInput.addEventListener('keydown', (event) => {
      handleAuthInputSubmit(event, loginWithEmail);
    });
  }

  if (elements.loadTaskBtn) {
    elements.loadTaskBtn.addEventListener('click', loadTask);
  }

  if (elements.taskIdInput) {
    elements.taskIdInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        loadTask();
      }
    });
  }

  if (elements.copyTaskIdBtn) {
    elements.copyTaskIdBtn.addEventListener('click', copyTaskId);
  }

  if (elements.rerunReviewBtn) {
    elements.rerunReviewBtn.addEventListener('click', rerunReview);
  }

  if (elements.inspectorTabs) {
    elements.inspectorTabs.addEventListener('click', (event) => {
      const button = event.target.closest('.tab-btn');
      if (!button) {
        return;
      }
      setActiveInspectorTab(button.dataset.tab);
    });
  }

  if (elements.artifactFilterBtn) {
    elements.artifactFilterBtn.addEventListener('click', () => {
      artifactTypeFilter = elements.artifactTypeInput?.value.trim() || '';
      lastArtifactSignature = '';
      if (currentTaskId) {
        pollArtifacts(currentTaskId);
      }
    });
  }

  if (elements.artifactTypeInput) {
    elements.artifactTypeInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        artifactTypeFilter = elements.artifactTypeInput?.value.trim() || '';
        lastArtifactSignature = '';
        if (currentTaskId) {
          pollArtifacts(currentTaskId);
        }
      }
    });
  }

  if (elements.fileCategories) {
    elements.fileCategories.addEventListener('click', (event) => {
      const category = event.target.closest('.category-item');
      if (!category) {
        return;
      }
      const nextCategory = category.dataset.category || 'all';
      if (nextCategory === activeFileCategory) {
        return;
      }
      activeFileCategory = nextCategory;
      renderFileCategories(latestFilesSnapshot);
      renderFileList(latestFilesSnapshot);
    });
  }

  if (elements.fileList) {
    elements.fileList.addEventListener('click', (event) => {
      const fileItem = event.target.closest('.file-item');
      if (!fileItem || !currentTaskId) {
        return;
      }
      const path = fileItem.dataset.path;
      if (!path) {
        return;
      }
      handleFileSelection(currentTaskId, path);
    });
  }

  if (elements.copyFileBtn) {
    elements.copyFileBtn.addEventListener('click', () => {
      copyFileContent();
    });
  }

  const downloadZip = async (taskId) => {
    if (!ensureAuthForAction()) {
      return;
    }
    const downloadUrl = buildApiUrl(`/api/tasks/${taskId}/download.zip`);
    try {
      const response = await apiFetch(downloadUrl);
      if (!response.ok) {
        const message = response.status === 401 || response.status === 403
          ? 'Invalid credentials or no access to this task.'
          : `Download failed (${response.status})`;
        showToast(message, '⚠️');
        return;
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = `task_${taskId}.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      showToast('Unable to download ZIP. Please try again.', '⚠️');
    }
  };

  const downloadGitExport = async (taskId) => {
    if (!ensureAuthForAction()) {
      return;
    }
    const downloadUrl = buildApiUrl(`/api/tasks/${taskId}/git-export.zip`);
    try {
      const response = await apiFetch(downloadUrl);
      if (!response.ok) {
        const message = response.status === 401 || response.status === 403
          ? 'Invalid credentials or no access to this task.'
          : `Download failed (${response.status})`;
        showToast(message, '⚠️');
        return;
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = `task_${taskId}_git_export.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      showToast('Unable to download git export. Please try again.', '⚠️');
    }
  };

  const readResponseJson = async (response) => {
    try {
      return await response.json();
    } catch (error) {
      return null;
    }
  };

  const formatApiDetail = (detail) => {
    if (!detail) {
      return '';
    }
    if (typeof detail === 'string') {
      return detail;
    }
    try {
      return JSON.stringify(detail);
    } catch (error) {
      return String(detail);
    }
  };

  const formatPrErrorMessage = (payload, status) => {
    if (!payload || typeof payload !== 'object') {
      return `PR creation failed (${status})`;
    }
    const rawMessage = payload.github_error_message
      || payload.message
      || payload.detail
      || payload.error;
    const baseMessage = formatApiDetail(rawMessage) || `PR creation failed (${status})`;
    const githubStatus = payload.status_code ? `GitHub ${payload.status_code}` : '';
    const responseDetail = payload.github_error_response
      ? formatApiDetail(payload.github_error_response)
      : '';
    const requestId = payload.request_id ? `request_id: ${payload.request_id}` : '';
    const parts = [githubStatus, baseMessage, responseDetail, requestId].filter(Boolean);
    return parts.join(' — ');
  };

  const createPullRequest = async (taskId) => {
    if (!taskId) {
      showToast('No task available for PR.', '⚠️');
      return;
    }
    if (!canCreatePr()) {
      showToast('Connect GitHub and complete the task to create a PR.', 'ℹ️');
      return;
    }
    setPrCreateStatus('');
    try {
      const response = await apiFetch(buildApiUrl(`/api/tasks/${taskId}/create-pr`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({})
      });
      if (!response.ok) {
        const errorPayload = await readResponseJson(response);
        const message = response.status === 401 || response.status === 403
          ? 'Sign in to create a PR.'
          : formatPrErrorMessage(errorPayload, response.status);
        setPrCreateStatus(message, 'error');
        showToast(message, '⚠️');
        return;
      }
      const data = await response.json();
      showToast('Pull request created.', '✅');
      setPrCreateStatus('Pull request created.');
      if (data.pull_request_url) {
        window.open(data.pull_request_url, '_blank', 'noopener');
      }
    } catch (error) {
      const message = error?.message || 'Unable to create PR.';
      setPrCreateStatus(message, 'error');
      showToast(message, '⚠️');
    }
  };

  if (elements.downloadZipBtn) {
    elements.downloadZipBtn.addEventListener('click', () => {
      if (!currentTaskId) {
        showToast('No task available to download.', '⚠️');
        return;
      }
      if (elements.downloadZipBtn.disabled) {
        showToast('ZIP download is available after completion.', 'ℹ️');
        return;
      }
      downloadZip(currentTaskId);
    });
  }

  ensureGitExportButton();

  if (elements.downloadGitExportBtn) {
    elements.downloadGitExportBtn.addEventListener('click', () => {
      if (!currentTaskId) {
        showToast('No task available to download.', '⚠️');
        return;
      }
      if (elements.downloadGitExportBtn.disabled) {
        showToast('Git export download is available after completion.', 'ℹ️');
        return;
      }
      downloadGitExport(currentTaskId);
    });
  }

  if (elements.createPrBtn) {
    elements.createPrBtn.addEventListener('click', () => {
      if (!currentTaskId) {
        showToast('No task available to create a PR.', '⚠️');
        return;
      }
      if (elements.createPrBtn.disabled) {
        showToast('Complete the task and connect GitHub to create a PR.', 'ℹ️');
        return;
      }
      createPullRequest(currentTaskId);
    });
  }

  if (elements.taskDescription) {
    elements.taskDescription.addEventListener('input', updateCharCount);
  }

  updateCharCount();
  hydrateStoredTokens();
  updateApiBaseUrl();
  updateAuthModeIndicator();
  updateAuthModeVisibility();
  updateIntakeVisibility(resolveInteractiveResearchEnabled(null));
  updateStartProcessingState({ canStart: false, interactiveEnabled: resolveInteractiveResearchEnabled(null) });
  updateAuthStatus();
  syncAccessTokenFromHash();
  updateApiKeyInputs(getStoredApiKey());
  updateAccessTokenInputs(getStoredAccessToken());
  void fetchRuntimeConfig()
    .then(() => validateAuthSession())
    .then(loadTemplates)
    .then(() => refreshDashboard({ silent: true }));
  setActiveInspectorTab(activeInspectorTab);
  updateTimeTakenDisplay({});
})();
