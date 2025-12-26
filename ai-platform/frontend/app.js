(() => {
  const API_BASE_URL =
    window.API_BASE_URL ||
    document.querySelector('meta[name="api-base-url"]')?.content ||
    '';

  const POLL_INTERVAL_MS = 1200;
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
    resultJson: document.getElementById('resultJson'),
    resultStatus: document.getElementById('resultStatus'),
    loadingOverlay: document.getElementById('loadingOverlay'),
    loadingMessage: document.getElementById('loadingMessage'),
    loadingSubtext: document.getElementById('loadingSubtext'),
    notificationToast: document.getElementById('notificationToast'),
    toastIcon: document.getElementById('toastIcon'),
    toastMessage: document.getElementById('toastMessage')
  };

  let currentTaskId = null;
  let pollingTimer = null;
  let pollStartTime = null;

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
  };

  const resetResultPanel = () => {
    if (elements.taskError) {
      elements.taskError.textContent = '';
      elements.taskError.classList.add('hidden');
    }
    if (elements.resultJson) {
      elements.resultJson.textContent = '';
    }
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
    if (pollingTimer) {
      clearTimeout(pollingTimer);
      pollingTimer = null;
    }
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
    pollingTimer = setTimeout(() => pollTask(taskId), POLL_INTERVAL_MS);
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

    try {
      const response = await fetch(`${API_BASE_URL}/api/tasks/${taskId}`);
      if (!response.ok) {
        throw new Error(`Status request failed (${response.status})`);
      }
      const data = await response.json();
      updateStatusPanel(data);

      const progressInfo = formatProgress(data.progress);
      const isCompletedByProgress =
        progressInfo.value >= 1 && String(data.current_stage).toLowerCase() === 'completed';
      const isTerminal = TERMINAL_STATUSES.has(String(data.status).toLowerCase()) ||
        isCompletedByProgress;

      if (isTerminal) {
        stopPolling();
        handleTerminalState(data);
        showSection(elements.taskResults);
        setSubmitDisabled(false);
        return;
      }

      schedulePoll(taskId);
    } catch (error) {
      stopPolling();
      if (elements.taskError) {
        elements.taskError.textContent = 'Unable to reach the backend. Please try again.';
        elements.taskError.classList.remove('hidden');
      }
      showToast('Unable to reach the backend. Please try again.', '⚠️');
      setSubmitDisabled(false);
    }
  };

  const startPolling = (taskId) => {
    stopPolling();
    pollStartTime = Date.now();
    schedulePoll(taskId);
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
      const response = await fetch(`${API_BASE_URL}/api/tasks`, {
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

      currentTaskId = taskId;
      if (elements.currentTaskId) {
        elements.currentTaskId.textContent = taskId;
      }
      if (elements.progressTime) {
        elements.progressTime.textContent = 'Started: Just now';
      }
      showSection(elements.taskProgress);
      updateStatusPanel({ status: 'queued', current_stage: 'starting', progress: 0 });
      setLoading(false);
      startPolling(taskId);
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

  if (elements.taskDescription) {
    elements.taskDescription.addEventListener('input', updateCharCount);
  }

  updateCharCount();
  updateApiBaseUrl();
})();
