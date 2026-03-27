const titleEl = document.getElementById("montage_title");
const audioFileEl = document.getElementById("audio_file");
const urlsWrapEl = document.getElementById("montage_urls");
const addUrlBtn = document.getElementById("add_url_btn");
const uploadLinkEl = document.getElementById("upload_link");

const createBtn = document.getElementById("create_montage_btn");
const statusEl = document.getElementById("status");
const resultBox = document.getElementById("resultBox");

const statusOverlayEl = document.getElementById("status_overlay");
const statusOverlayTextEl = document.getElementById("status_overlay_text");
let statusOverlayProgressEl = null;
let statusOverlayProgressBarEl = null;
let statusOverlayProgressValueEl = null;

let busy = false;
let overlayHideTimer = null;
let activeMontageJobId = null;

const MAX_URL_FIELDS = 4;
const MONTAGE_DRAFT_KEY = "create_video_draft_v1";
const MONTAGE_RESULT_KEY = "create_video_result_v1";
const GENERATED_VIDEO_KEY = "current_generated_video_v1";

function isPageReloadNavigation() {
  try {
    const navEntries = performance.getEntriesByType?.("navigation") || [];
    if (navEntries.length > 0) {
      return navEntries[0].type === "reload";
    }
    return performance.navigation?.type === 1;
  } catch {
    return false;
  }
}

function getUrlInputs() {
  return Array.from(document.querySelectorAll(".montage-url"));
}

function readJsonStorage(key, fallback = {}) {
  try {
    return JSON.parse(sessionStorage.getItem(key) || JSON.stringify(fallback));
  } catch {
    return fallback;
  }
}

function saveDraft() {
  const draft = {
    title: String(titleEl?.value || "").trim(),
    urls: getUrlInputs().map((el) => String(el.value || "").trim()).filter(Boolean),
  };
  sessionStorage.setItem(MONTAGE_DRAFT_KEY, JSON.stringify(draft));
}

function restoreDraft() {
  const draft = readJsonStorage(MONTAGE_DRAFT_KEY, {});
  const hasTitleQuery = new URLSearchParams(window.location.search).has("title");

  if (!hasTitleQuery && draft.title) {
    titleEl.value = draft.title;
  }

  if (Array.isArray(draft.urls) && draft.urls.length > 0) {
    urlsWrapEl.innerHTML = "";
    draft.urls.slice(0, MAX_URL_FIELDS).forEach((url, index) => {
      let row;
      if (index === 0) {
        row = document.createElement("div");
        row.className = "montage-url-row";
        row.innerHTML = '<input class="form-control glitch-input montage-url" type="text" placeholder="https://www.youtube.com/watch?v=...">';
      } else {
        row = createUrlRow();
      }
      const input = row.querySelector(".montage-url");
      if (input) input.value = url;
      urlsWrapEl.appendChild(row);
    });
  }
}

function syncUploadHref() {
  if (!uploadLinkEl || !titleEl) return;
  const title = String(titleEl.value || "").trim();
  uploadLinkEl.href = title ? `/?title=${encodeURIComponent(title)}` : "/";
}

function createUrlRow() {
  const row = document.createElement("div");
  row.className = "montage-url-row d-flex gap-2 align-items-center";
  row.innerHTML = `
    <input class="form-control glitch-input montage-url" type="text" placeholder="https://www.youtube.com/watch?v=...">
    <button type="button" class="btn btn-outline-danger btn-sm glitch-btn glitch-btn--sm montage-remove-url" data-text="X">
      <span class="btn-text">X</span>
    </button>
  `;

  row.querySelector(".montage-remove-url").addEventListener("click", () => {
    row.remove();
    ensureUrlControlsState();
    saveDraft();
  });

  return row;
}

function ensureUrlControlsState() {
  const inputs = getUrlInputs();
  addUrlBtn.disabled = busy || inputs.length >= MAX_URL_FIELDS;

  const removeButtons = Array.from(document.querySelectorAll(".montage-remove-url"));
  for (const btn of removeButtons) {
    btn.disabled = busy;
  }
}

function ensureOverlayProgressUi() {
  if (statusOverlayProgressEl || !statusOverlayTextEl) return;
  const bodyEl = statusOverlayTextEl.parentElement;
  if (!bodyEl) return;

  const progressWrap = document.createElement("div");
  progressWrap.className = "status-overlay__progress";
  progressWrap.setAttribute("aria-hidden", "true");
  progressWrap.innerHTML = `
    <div class="status-overlay__progress-track">
      <div class="status-overlay__progress-bar"></div>
    </div>
    <div class="status-overlay__progress-value">0%</div>
  `;

  bodyEl.appendChild(progressWrap);
  statusOverlayProgressEl = progressWrap;
  statusOverlayProgressBarEl = progressWrap.querySelector(".status-overlay__progress-bar");
  statusOverlayProgressValueEl = progressWrap.querySelector(".status-overlay__progress-value");
}

function renderOverlayProgress(value) {
  ensureOverlayProgressUi();
  if (!statusOverlayProgressEl || !statusOverlayProgressBarEl || !statusOverlayProgressValueEl) return;
  const safeValue = Math.max(0, Math.min(100, Number(value) || 0));
  statusOverlayProgressEl.classList.add("is-visible");
  statusOverlayProgressBarEl.style.width = `${safeValue}%`;
  statusOverlayProgressValueEl.textContent = `${Math.round(safeValue)}%`;
}

function resetOverlayProgress() {
  ensureOverlayProgressUi();
  if (!statusOverlayProgressEl || !statusOverlayProgressBarEl || !statusOverlayProgressValueEl) return;
  statusOverlayProgressEl.classList.remove("is-visible");
  statusOverlayProgressBarEl.style.width = "0%";
  statusOverlayProgressValueEl.textContent = "0%";
}

function setBusy(disabled) {
  busy = !!disabled;
  createBtn.disabled = busy;
  titleEl.disabled = busy;
  audioFileEl.disabled = busy;

  for (const input of getUrlInputs()) {
    input.disabled = busy;
  }

  ensureUrlControlsState();
}

function setStatus(message, progress = null) {
  const text = String(message || "").trim();
  if (statusEl) statusEl.textContent = text;

  if (overlayHideTimer) {
    clearTimeout(overlayHideTimer);
    overlayHideTimer = null;
  }

  if (!text) {
    statusOverlayEl?.classList.remove("is-visible", "is-busy", "is-success", "is-error");
    resetOverlayProgress();
    return;
  }

  const lower = text.toLowerCase();
  const isError = lower.includes("ошибка") || lower.includes("error");
  const isSuccess = lower.includes("готов") || lower.includes("успех") || lower.includes("success");
  const isBusy = !isError && !isSuccess;

  if (!statusOverlayEl || !statusOverlayTextEl) return;

  statusOverlayTextEl.textContent = text;
  statusOverlayEl.classList.add("is-visible");
  statusOverlayEl.classList.toggle("is-busy", isBusy);
  statusOverlayEl.classList.toggle("is-success", isSuccess);
  statusOverlayEl.classList.toggle("is-error", isError);

  if (progress !== null) {
    renderOverlayProgress(progress);
  } else if (!isBusy) {
    renderOverlayProgress(100);
  }

  if (!isBusy) {
    overlayHideTimer = window.setTimeout(() => {
      statusOverlayEl.classList.remove("is-visible", "is-busy", "is-success", "is-error");
      resetOverlayProgress();
      overlayHideTimer = null;
    }, 2200);
  }
}

function showError(message) {
  resultBox.classList.remove("d-none", "alert-success");
  resultBox.classList.add("alert", "alert-danger");
  resultBox.textContent = message;
}

function buildShortsHtml(shorts) {
  if (!Array.isArray(shorts) || shorts.length === 0) return "";
  return `
    <div class="mt-4">
      <div class="mb-2"><b>Shorts:</b></div>
      <div class="d-grid gap-3">
        ${shorts.map((short) => `
          <div class="border rounded p-3">
            <div class="mb-2"><b>Short ${short.index || ""}</b> • ${short.filename || ""}</div>
            <div class="mb-2"><b>Shots:</b> ${short.shots_count ?? "-"} | <b>Source events:</b> ${short.source_events_count ?? "-"}</div>
            <video class="w-100 rounded border mb-2" controls preload="metadata" style="background:#000; max-height: 420px;">
              <source src="${short.download_url}" type="video/mp4">
            </video>
            <a class="btn btn-outline-success btn-sm glitch-btn glitch-btn--sm" href="${short.download_url}" data-text="СКАЧАТЬ SHORT">
              <span class="btn-text">СКАЧАТЬ SHORT</span>
            </a>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function buildSuccessHtml(data) {
  const mode = String(data.mode || "video");
  const hasMain = !!(data.filename && data.download_url);
  const shortsHtml = buildShortsHtml(data.shorts || []);

  if (mode === "shorts" && !hasMain) {
    return `
      <div class="mb-3 text-success"><b>SHORTS READY:</b> Готовые shorts сохранены на сервере.</div>
      ${shortsHtml}
    `;
  }

  return `
    <div class="mb-2"><b>Файл:</b> ${data.filename}</div>
    <div class="mb-2"><b>Shots:</b> ${data.shots_count} | <b>Source events:</b> ${data.source_events_count}</div>
    <div class="mb-3"><b>Intro:</b> ${data.intro_tag} / ${data.intro_title} / ${data.intro_artist}</div>
    <div class="mb-3 text-success"><b>UPLOAD:</b> Готовый файл уже сохранён на сервере и будет доступен на вкладке Upload.</div>
    <div class="mb-3">
      <video class="w-100 rounded border" controls preload="metadata" style="background:#000; max-height: 420px;">
        <source src="${data.download_url}" type="video/mp4">
      </video>
    </div>
    <a class="btn btn-outline-success btn-sm glitch-btn glitch-btn--sm" href="${data.download_url}" data-text="СКАЧАТЬ MP4">
      <span class="btn-text">СКАЧАТЬ MP4</span>
    </a>
    ${shortsHtml}
  `;
}

function showSuccess(data) {
  resultBox.classList.remove("d-none", "alert-danger");
  resultBox.classList.add("alert", "alert-success");
  resultBox.innerHTML = buildSuccessHtml(data);
}

function clearResult({ clearStored = true } = {}) {
  resultBox.classList.add("d-none");
  resultBox.classList.remove("alert-success", "alert-danger");
  resultBox.innerHTML = "";
  if (clearStored) {
    sessionStorage.removeItem(MONTAGE_RESULT_KEY);
  }
}

function saveResult(data) {
  sessionStorage.setItem(MONTAGE_RESULT_KEY, JSON.stringify(data));
}

function restoreResult() {
  if (isPageReloadNavigation()) {
    sessionStorage.removeItem(MONTAGE_RESULT_KEY);
    return;
  }

  const data = readJsonStorage(MONTAGE_RESULT_KEY, null);
  if (!data) return;
  showSuccess(data);
}

async function safeJson(response) {
  const raw = await response.text();
  try {
    return { ok: response.ok, status: response.status, data: JSON.parse(raw), raw };
  } catch {
    return { ok: response.ok, status: response.status, data: null, raw };
  }
}

function isValidYouTubeUrl(value) {
  return /^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\//i.test(String(value || "").trim());
}

function getFilledUrls() {
  return getUrlInputs().map((el) => el.value.trim()).filter(Boolean);
}

async function pollMontageProgress(jobId, title) {
  activeMontageJobId = jobId;

  while (activeMontageJobId === jobId) {
    const response = await fetch(`/api/montage/progress/${jobId}`, {
      credentials: "same-origin",
      cache: "no-store",
    });
    const payload = await safeJson(response);

    if (!payload.ok || !payload.data) {
      throw new Error(payload.data?.detail || payload.raw || "Не удалось получить состояние монтажа.");
    }

    const data = payload.data;
    const phase = String(data.phase || "Собираю монтаж...");
    const detail = String(data.detail || "").trim();
    const progress = Number(data.progress || 0);
    const statusText = detail ? `${phase} • ${detail}` : phase;
    setStatus(statusText, progress);

    if (data.status === "success" && data.result) {
      const resultData = { ...data.result };

      if (resultData.filename && resultData.download_url) {
        const generatedVideoData = {
          filename: resultData.filename,
          download_url: resultData.download_url,
          title,
          created_at: Date.now(),
        };
        sessionStorage.setItem(GENERATED_VIDEO_KEY, JSON.stringify(generatedVideoData));
      } else {
        sessionStorage.removeItem(GENERATED_VIDEO_KEY);
      }

      saveResult(resultData);
      setStatus("Монтаж готов", 100);
      showSuccess(resultData);
      activeMontageJobId = null;
      return;
    }

    if (data.status === "error") {
      activeMontageJobId = null;
      throw new Error(data.error || data.detail || "Не удалось собрать монтаж.");
    }

    await new Promise((resolve) => window.setTimeout(resolve, 700));
  }
}

restoreDraft();
restoreResult();
syncUploadHref();
ensureOverlayProgressUi();
resetOverlayProgress();

titleEl?.addEventListener("input", () => {
  syncUploadHref();
  saveDraft();
});

urlsWrapEl?.addEventListener("input", saveDraft);

audioFileEl?.addEventListener("change", () => {
  clearResult();
});

addUrlBtn.addEventListener("click", () => {
  if (busy) return;
  if (getUrlInputs().length >= MAX_URL_FIELDS) return;
  urlsWrapEl.appendChild(createUrlRow());
  ensureUrlControlsState();
  saveDraft();
});

createBtn.addEventListener("click", async () => {
  if (busy) return;
  clearResult();

  const title = titleEl.value.trim();
  if (!audioFileEl.files?.length) {
    showError("Выбери аудиофайл для монтажа.");
    return;
  }
  if (!title) {
    showError("Укажи название видео.");
    return;
  }

  const urls = getFilledUrls();
  if (urls.length === 0) {
    showError("Нужна хотя бы одна YouTube ссылка.");
    return;
  }

  const invalidUrl = urls.find((url) => !isValidYouTubeUrl(url));
  if (invalidUrl) {
    showError(`Некорректная YouTube ссылка: ${invalidUrl}`);
    return;
  }

  const fd = new FormData();
  fd.append("title", title);
  fd.append("audio_file", audioFileEl.files[0]);
  for (const url of urls) {
    fd.append("youtube_urls", url);
  }

  try {
    setBusy(true);
    setStatus("Создаю видео...", 0);

    const response = await fetch("/api/montage/create", {
      method: "POST",
      body: fd,
      credentials: "same-origin",
    });

    const payload = await safeJson(response);
    if (!payload.ok || !payload.data?.job_id) {
      throw new Error(payload.data?.detail || payload.raw || "Не удалось запустить монтаж.");
    }

    await pollMontageProgress(payload.data.job_id, title);
  } catch (error) {
    console.error(error);
    setStatus("Ошибка", 100);
    showError(error.message || "Не удалось собрать монтаж.");
  } finally {
    activeMontageJobId = null;
    setBusy(false);
  }
});

ensureUrlControlsState();
