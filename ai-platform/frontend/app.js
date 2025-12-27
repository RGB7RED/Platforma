(() => {
  const resolveApiBaseUrl = () => {
    const configValue = window.__APP_CONFIG__?.API_BASE_URL;
    if (typeof configValue === 'string' && configValue.trim()) {
      return configValue.trim();
    }
    const metaValue = document.querySelector('meta[name="api-base-url"]')?.content;
    if (typeof metaValue === 'string' && metaValue.trim()) {
      return metaValue.trim();
    }
    return '';
  };

  const API_BASE_URL = resolveApiBaseUrl();
  const normalizeBaseUrl = (value) => value.replace(/\/+$/, '');
  const normalizePath = (value) => (value.startsWith('/') ? value : `/${value}`);
  const buildApiUrl = (path) => {
    const resolvedPath = normalizePath(path);
    if (!API_BASE_URL) {
      return resolvedPath;
    }
    return `${normalizeBaseUrl(API_BASE_URL)}${resolvedPath}`;
  };
  const buildWebSocketUrl = (taskId) => {
    const wsPath = `/ws/${taskId}`;
    const fallbackProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    if (!API_BASE_URL) {
      return `${fallbackProtocol}://${window.location.host}${wsPath}`;
    }
    try {
      const apiUrl = new URL(API_BASE_URL);
      const wsProtocol = apiUrl.protocol === 'https:' ? 'wss:' : 'ws:';
      const basePath = apiUrl.pathname.replace(/\/+$/, '');
      return `${wsProtocol}//${apiUrl.host}${basePath}${wsPath}`;
    } catch (error) {
      return `${fallbackProtocol}://${window.location.host}${wsPath}`;
    }
  };

  const POLL_INTERVAL_MS = 2000;
  const POLL_SLOW_INTERVAL_MS = 4000;
  const POLL_TIMEOUT_MS = 3 * 60 * 1000;
  const TERMINAL_STATUSES = new Set(['completed', 'failed', 'error']);

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
    codexVersion: document.getElementById('codexVersion'),
    currentTaskId: document.getElementById('currentTaskId'),
    progressBarFill: document.getElementById('progressBarFill'),
    progressPercentage: document.getElementById('progressPercentage'),
    progressTime: document.getElementById('progressTime'),
    currentStage: document.getElementById('currentStage'),
    taskStatus: document.getElementById('taskStatus'),
    apiBaseUrl: document.getElementById('apiBaseUrl'),
    taskError: document.getElementById('taskError'),
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
    loadingOverlay: document.getElementById('loadingOverlay'),
    loadingMessage: document.getElementById('loadingMessage'),
    loadingSubtext: document.getElementById('loadingSubtext'),
    notificationToast: document.getElementById('notificationToast'),
    toastIcon: document.getElementById('toastIcon'),
    toastMessage: document.getElementById('toastMessage')
  };

  let currentTaskId = null;
  let pollStartTime = null;
  let pollingIntervals = {
    status: null,
    state: null,
    events: null,
    artifacts: null,
    files: null
  };
  let lastEventSignature = '';
  let lastArtifactSignature = '';
  let artifactTypeFilter = '';
  let activeInspectorTab = 'state';
  let latestFilesTotal = null;
  let latestArtifactsTotal = null;
  let activeSocket = null;

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
    if (!elements.apiBaseUrl) {
      return;
    }
    elements.apiBaseUrl.textContent = API_BASE_URL || '(same origin)';
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
    fallbackFiles,
    fallbackArtifacts
  } = {}) => {
    const resolvedFiles =
      typeof filesTotal === 'number' ? filesTotal : fallbackFiles ?? 0;
    const resolvedArtifacts =
      typeof artifactsTotal === 'number' ? artifactsTotal : fallbackArtifacts ?? 0;
    renderCount(elements.filesCount, resolvedFiles);
    renderCount(elements.artifactsCount, resolvedArtifacts);
  };

  const formatProgress = (progress) => {
    if (typeof progress !== 'number' || Number.isNaN(progress)) {
      return { value: 0, percent: 0 };
    }
    const normalized = progress > 1 ? progress / 100 : progress;
    const clamped = Math.max(0, Math.min(1, normalized));
    return { value: clamped, percent: Math.round(clamped * 100) };
  };

  const updateStatusPanel = (data) => {
    if (!data) {
      return;
    }
    if (elements.taskStatus) {
      elements.taskStatus.textContent = data.status || '-';
    }
    if (elements.currentStage) {
      elements.currentStage.textContent = data.current_stage || '-';
    }
    const progressInfo = formatProgress(data.progress);
    if (elements.progressPercentage) {
      elements.progressPercentage.textContent = `${progressInfo.percent}%`;
    }
    if (elements.progressBarFill) {
      elements.progressBarFill.style.width = `${progressInfo.percent}%`;
    }
    if (elements.taskError) {
      elements.taskError.textContent = data.error || '';
      elements.taskError.classList.toggle('hidden', !data.error);
    }
    if (elements.resultJson && data.result !== undefined && data.result !== null) {
      elements.resultJson.textContent = JSON.stringify(data.result, null, 2);
    }
    updateSummaryCounts({
      fallbackFiles: typeof data.files_count === 'number' ? data.files_count : null,
      fallbackArtifacts:
        typeof data.artifacts_count === 'number' ? data.artifacts_count : null
    });
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
    updateSummaryCounts({ filesTotal: 0, artifactsTotal: 0 });
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
      const response = await fetch(url);
      if (!response.ok) {
        const message = response.status === 501
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

  const getItemKey = (item) =>
    item?.id || item?._id || item?.event_id || item?.artifact_id || item?.created_at || '';

  const renderStatePanel = (state) => {
    if (!elements.stateTable) {
      return;
    }
    const entries = [
      { label: 'status', value: state?.status },
      { label: 'progress', value: state?.progress },
      { label: 'current_stage', value: state?.current_stage },
      { label: 'active_role', value: state?.active_role },
      { label: 'current_task', value: state?.current_task },
      { label: 'container_state', value: state?.container_state },
      { label: 'container_progress', value: state?.container_progress },
      { label: 'updated_at', value: formatShortDate(state?.updated_at) }
    ];
    elements.stateTable.innerHTML = entries
      .map(
        (entry) => `
          <div class="state-item">
            <span>${entry.label}</span>
            <strong>${entry.value ?? '-'}</strong>
          </div>
        `
      )
      .join('');
  };

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

  const renderArtifacts = (artifacts) => {
    if (!elements.artifactsList) {
      return;
    }
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
              <summary>${formatPayloadSummary(payload)}</summary>
              <pre>${JSON.stringify(payload, null, 2)}</pre>
            </details>
          </div>
        `;
      })
      .join('');
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
      updateStatusPanel(data);

      const progressInfo = formatProgress(data.progress);
      const isCompletedByProgress =
        progressInfo.value >= 1 && String(data.current_stage).toLowerCase() === 'completed';
      const isTerminal = isTerminalState(data);

      if (isTerminal) {
        await Promise.all([pollFiles(taskId), pollArtifacts(taskId)]);
        stopPolling();
        handleTerminalState(data);
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
    const total = parseTotalCount(data);
    if (typeof total === 'number') {
      latestArtifactsTotal = total;
      updateSummaryCounts();
    }
    const signature = JSON.stringify(artifacts.slice(0, 20).map(getItemKey));
    if (signature === lastArtifactSignature) {
      return;
    }
    lastArtifactSignature = signature;
    renderArtifacts(artifacts);
  };

  const pollFiles = async (taskId) => {
    const { data, error } = await fetchFiles(taskId);
    if (error) {
      return;
    }
    const total = parseTotalCount(data);
    if (typeof total === 'number') {
      latestFilesTotal = total;
      updateSummaryCounts();
    }
  };

  const startPolling = (taskId) => {
    stopPolling();
    pollStartTime = Date.now();
    lastEventSignature = '';
    lastArtifactSignature = '';
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

  const startWebSocket = (taskId) => {
    closeWebSocket();
    const wsUrl = buildWebSocketUrl(taskId);
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
        updateStatusPanel(payload);
        if (isTerminalState(payload)) {
          await Promise.all([pollFiles(taskId), pollArtifacts(taskId)]);
          stopPolling();
          handleTerminalState(payload);
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
    startWebSocket(taskId);
  };

  const submitTask = async () => {
    const description = elements.taskDescription?.value.trim();
    if (!description) {
      showToast('Please enter a task description.', '⚠️');
      return;
    }

    setSubmitDisabled(true);
    resetResultPanel();
    setLoading(true, 'Creating task...', 'Submitting your request to the AI platform');

    const payload = { description };
    const codexValue = elements.codexVersion?.value?.trim();
    if (codexValue) {
      payload.codex_version = codexValue;
    }
    if (window.USER_ID) {
      payload.user_id = window.USER_ID;
    }

    try {
      const response = await fetch(buildApiUrl('/api/tasks'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        throw new Error(`Request failed (${response.status})`);
      }

      const data = await response.json();
      const taskId = data.task_id || data.id;
      if (!taskId) {
        throw new Error('Task ID not returned from server');
      }

      if (elements.progressTime) {
        elements.progressTime.textContent = 'Started: Just now';
      }
      activateTask(taskId, { focusState: true });
      updateStatusPanel({ status: 'queued', current_stage: 'starting', progress: 0 });
      setLoading(false);
    } catch (error) {
      setLoading(false);
      setSubmitDisabled(false);
      if (elements.taskError) {
        elements.taskError.textContent = 'Unable to create task. Please try again.';
        elements.taskError.classList.remove('hidden');
      }
      showToast('Unable to create task. Please try again.', '⚠️');
    }
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
  };

  const loadTask = () => {
    const taskId = elements.taskIdInput?.value.trim();
    if (!taskId) {
      showToast('Please enter a task_id to load.', '⚠️');
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
    });
  }

  if (elements.refreshProgressBtn) {
    elements.refreshProgressBtn.addEventListener('click', refreshStatus);
  }

  if (elements.submitTaskBtn) {
    elements.submitTaskBtn.addEventListener('click', submitTask);
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

  if (elements.taskDescription) {
    elements.taskDescription.addEventListener('input', updateCharCount);
  }

  updateCharCount();
  updateApiBaseUrl();
  setActiveInspectorTab(activeInspectorTab);
})();
