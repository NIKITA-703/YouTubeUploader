const titleEl = document.getElementById("title");
const videoEl = document.getElementById("video_file");
const hashtagsEl = document.getElementById("hashtags");
const seoEl = document.getElementById("seo_tags");
const publishEl = document.getElementById("publish_dt");

const fillBtn = document.getElementById("fill_btn");
const clearBtn = document.getElementById("clear_btn");
const uploadBtn = document.getElementById("upload_btn");
const refreshPreviewBtn = document.getElementById("refresh_preview_btn");

const previewImg = document.getElementById("preview_img");
const previewFilenameEl = document.getElementById("preview_filename");
const previewFileEl = document.getElementById("preview_file");
const serverVideoFilenameEl = document.getElementById("server_video_filename");
const serverVideoPanelEl = document.getElementById("server_video_panel");
const serverVideoMetaEl = document.getElementById("server_video_meta");
const clearServerVideoBtn = document.getElementById("clear_server_video_btn");

const statusEl = document.getElementById("status");
const statusOverlayEl = document.getElementById("status_overlay");
const statusOverlayTextEl = document.getElementById("status_overlay_text");
const resultBox = document.getElementById("resultBox");

const uploadProgressWrap = document.getElementById("uploadProgressWrap");
const uploadProgressBar = document.getElementById("uploadProgressBar");

const regenHashtagsBtn = document.getElementById("regen_hashtags_btn");
const regenSeoBtn = document.getElementById("regen_seo_btn");

const purchaseLinkEl = document.getElementById("purchase_link");
const createVideoLinkEl = document.getElementById("create_video_link");
const GENERATED_VIDEO_KEY = "current_generated_video_v1";

const bpmEl = document.getElementById("bpm");
const keyEl = document.getElementById("key");


// gallery
const galleryEl = document.getElementById("preview_gallery");
const refreshGalleryBtn = document.getElementById("refresh_gallery_btn");
const opsLogsEl = document.getElementById("ops_logs");
const refreshOpsBtn = document.getElementById("refresh_ops_btn");

const successSound = new Audio("/static/sounds/success.mp3");
successSound.volume = 0.5;  // Уровень громкости (от 0 до 1)

const lightbox = document.getElementById("glitch-lightbox");
const lightboxImg = document.getElementById("lightbox_img");
const lightboxCaption = document.getElementById("lightbox_caption");

let statusOverlayHideTimer = null;
let localPreviewUrl = null;
let uiBusy = false;
let calendarDutyStates = new Map();
let calendarDutyReqSeq = 0;

const backendActionButtons = [
  fillBtn,
  clearBtn,
  regenHashtagsBtn,
  regenSeoBtn,
  refreshPreviewBtn,
  refreshGalleryBtn,
  uploadBtn,
].filter(Boolean);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function safeCssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") {
    return window.CSS.escape(value);
  }
  return String(value).replace(/["\\]/g, "\\$&");
}

function syncCreateVideoHref() {
  if (!createVideoLinkEl || !titleEl) return;
  const title = String(titleEl.value || "").trim();
  createVideoLinkEl.href = title ? `/create-video?title=${encodeURIComponent(title)}` : "/create-video";
}

function readGeneratedVideoDraft() {
  try {
    return JSON.parse(sessionStorage.getItem(GENERATED_VIDEO_KEY) || "null");
  } catch {
    return null;
  }
}

function clearGeneratedVideoSelection(clearSession = true) {
  if (clearSession) {
    sessionStorage.removeItem(GENERATED_VIDEO_KEY);
  }
  if (serverVideoFilenameEl) serverVideoFilenameEl.value = "";
  if (serverVideoPanelEl) serverVideoPanelEl.classList.add("d-none");
  if (serverVideoMetaEl) serverVideoMetaEl.textContent = "";
}

function applyGeneratedVideoSelection(video) {
  if (!video?.filename || !serverVideoFilenameEl) return;
  serverVideoFilenameEl.value = video.filename;
  if (serverVideoPanelEl) serverVideoPanelEl.classList.remove("d-none");
  if (serverVideoMetaEl) {
    const title = String(video.title || "").trim();
    serverVideoMetaEl.textContent = title
      ? `Выбран готовое видео: ${title}`
      : `Выбран готовое видео: ${video.filename}`;
  }
}

function loadGeneratedVideoSelection() {
  const video = readGeneratedVideoDraft();
  if (!video?.filename) {
    clearGeneratedVideoSelection(false);
    return;
  }
  applyGeneratedVideoSelection(video);
}

function setBackendButtonsDisabled(disabled) {
  for (const btn of backendActionButtons) {
    btn.disabled = !!disabled;
  }
}

function setStatus(message) {
  const text = String(message || "").trim();
  if (statusEl) statusEl.textContent = text;
  if (!statusOverlayEl || !statusOverlayTextEl) return;

  if (statusOverlayHideTimer) {
    clearTimeout(statusOverlayHideTimer);
    statusOverlayHideTimer = null;
  }

  if (!text) {
    uiBusy = false;
    setBackendButtonsDisabled(false);
    statusOverlayEl.classList.remove("is-visible", "is-error", "is-success", "is-busy");
    return;
  }

  const lower = text.toLowerCase();
  const isError = /(ошибка|error)/i.test(lower);
  const isSuccess =
    text.includes("✅") ||
    /(готово|обновлен|обновлена|обновлены|выбрано|очищено|успех|success)/i.test(lower);
  const isBusy = !isError && !isSuccess;

  uiBusy = isBusy;
  setBackendButtonsDisabled(isBusy);

  statusOverlayTextEl.textContent = text;
  statusOverlayEl.classList.add("is-visible");
  statusOverlayEl.classList.toggle("is-error", isError);
  statusOverlayEl.classList.toggle("is-success", isSuccess);
  statusOverlayEl.classList.toggle("is-busy", isBusy);

  if (!isBusy) {
    statusOverlayHideTimer = setTimeout(() => {
      statusOverlayEl.classList.remove("is-visible", "is-error", "is-success", "is-busy");
      statusOverlayHideTimer = null;
    }, 2200);
  }
}

function normalizeAndValidateBpm(raw) {
  const cleaned = String(raw || "").replace(/\D+/g, "").trim();
  if (!cleaned) return "";
  const value = Number(cleaned);
  if (!Number.isInteger(value) || value < 0 || value > 250) {
    throw new Error("BPM должен быть числом от 0 до 250");
  }
  return String(value);
}

function hideResult() {
  if (!resultBox) return;
  resultBox.classList.add("d-none");
  resultBox.classList.remove("alert", "alert-success", "alert-danger");
  resultBox.innerHTML = "";
}

function showError(message) {
  if (!resultBox) return;
  resultBox.classList.remove("d-none");
  resultBox.classList.add("alert", "alert-danger");
  resultBox.classList.remove("alert-success");
  resultBox.textContent = message;
}

function showSuccessHtml(html) {
  if (!resultBox) return;
  resultBox.classList.remove("d-none");
  resultBox.classList.add("alert", "alert-success");
  resultBox.classList.remove("alert-danger");
  resultBox.innerHTML = html;
}

async function safeJson(res) {
  const text = await res.text();
  try {
    return { ok: res.ok, status: res.status, data: JSON.parse(text), raw: text };
  } catch {
    return { ok: res.ok, status: res.status, data: null, raw: text };
  }
}

function triggerGlitchToast() {
  const toast = document.getElementById("glitch-toast-container");
  if (!toast) return;

  setTimeout(() => {
    successSound.currentTime = 0;
    successSound.play().catch((err) => {
      console.log("Звук заблокирован до взаимодействия со страницей:", err);
    });
  }, 100);

  toast.classList.add("show");
  setTimeout(() => {
    toast.classList.remove("show");
  }, 4000);
}

function openZoom(src, caption) {
  if (!lightbox || !lightboxImg) return;
  lightboxImg.src = "";
  lightbox.style.display = "block";
  lightboxImg.src = src;
  if (lightboxCaption) {
    lightboxCaption.textContent = caption || "Увеличенное превью";
  }
  document.body.style.overflow = "hidden";
}

function closeZoom() {
  if (!lightbox) return;
  lightbox.style.display = "none";
  document.body.style.overflow = "auto";
}

function renderGallery(items) {
  if (!galleryEl) return;
  galleryEl.innerHTML = "";

  if (!items || items.length === 0) {
    galleryEl.innerHTML = `<div class="text-muted small">Превью пока нет в галерее.</div>`;
    return;
  }

  function selectPreview(name, url) {
    if (previewFileEl) previewFileEl.value = "";

    if (localPreviewUrl) {
      URL.revokeObjectURL(localPreviewUrl);
      localPreviewUrl = null;
    }

    if (previewFilenameEl) previewFilenameEl.value = name;
    if (previewImg) previewImg.src = `${url}?t=${Date.now()}`;
    setStatus("Превью выбрано ✅");

    const cards = galleryEl.querySelectorAll(".preview-card");
    for (const card of cards) card.classList.remove("selected");
    const active = galleryEl.querySelector(`.preview-card[data-name="${safeCssEscape(name)}"]`);
    if (active) active.classList.add("selected");
  }

  for (const item of items) {
    const col = document.createElement("div");
    col.className = "col-6 col-md-4";
    col.innerHTML = `
      <div class="card preview-card h-100" data-name="${escapeHtml(item.name)}">
        <img src="${escapeHtml(item.url)}" class="card-img-top preview-thumb" alt="${escapeHtml(item.name)}">
        <div class="card-body p-2">
          <div class="small text-truncate" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
          <button type="button"
                  class="btn btn-sm btn-primary w-100 mt-1 glitch-primary-like-login"
                  data-text="Выбрать">
            <span class="btn-text">Выбрать</span>
          </button>
        </div>
      </div>
    `;

    const card = col.querySelector(".preview-card");
    const btn = col.querySelector("button");
    const img = col.querySelector("img");

    btn?.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      selectPreview(item.name, item.url);
    });

    if (img) {
      img.style.cursor = "zoom-in";
      img.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        openZoom(item.url, item.name);
      });
    }

    card?.addEventListener("click", (e) => {
      if (e.target !== img) {
        selectPreview(item.name, item.url);
      }
    });

    galleryEl.appendChild(col);
  }
}

async function loadGallery() {
  const res = await fetch("/api/previews");
  const parsed = await safeJson(res);
  if (!parsed.ok) {
    console.warn("Gallery error:", parsed.raw);
    renderGallery([]);
    return;
  }
  renderGallery(parsed.data.items || []);
}

function renderOpsLogs(items) {
  if (!opsLogsEl) return;
  if (!items || items.length === 0) {
    opsLogsEl.innerHTML = `<div class="text-muted">Логов пока нет.</div>`;
    return;
  }

  const parseDetails = (raw) => {
    const text = String(raw || "").trim();
    if (!text || !(text.startsWith("{") || text.startsWith("["))) return null;
    try {
      return JSON.parse(text);
    } catch {
      return null;
    }
  };

  const pickVideoUrl = (detailsObj, detailsText) => {
    if (detailsObj?.video_url) return String(detailsObj.video_url);
    if (detailsObj?.video_id) return `https://youtu.be/${detailsObj.video_id}`;
    const match = String(detailsText || "").match(/video_id=([A-Za-z0-9_-]+)/);
    if (match) return `https://youtu.be/${match[1]}`;
    return "";
  };

  const used = new Set();
  const cards = [];

  for (let i = 0; i < items.length; i += 1) {
    if (used.has(i)) continue;
    const finish = items[i];
    const finishEvent = String(finish.event || "");
    if (finishEvent !== "upload_finished") continue;

    const finishDetailsRaw = String(finish.details || "");
    const finishDetailsObj = parseDetails(finishDetailsRaw) || {};
    const opId = String(finishDetailsObj.op_id || "").trim();
    const userRaw = String(finish.username || "-");
    const tsRaw = String(finish.created_at || "");
    const lvl = escapeHtml(String(finish.level || "INFO"));
    const st = escapeHtml(String(finish.status || "-"));
    let titleRaw = String(finishDetailsObj.title || "").trim();
    const uploadedAt = escapeHtml(String(finishDetailsObj.uploaded_at_msk || tsRaw));
    const publishAt = escapeHtml(String(finishDetailsObj.publish_at || ""));
    const videoUrl = escapeHtml(pickVideoUrl(finishDetailsObj, finishDetailsRaw));

    const techRows = [];
    for (let j = i + 1; j < items.length; j += 1) {
      if (used.has(j)) continue;
      const row = items[j];
      const rowEvent = String(row.event || "");
      if (rowEvent === "upload_finished") break;
      if (rowEvent !== "upload_started" && rowEvent !== "youtube_upload_started") continue;
      if (String(row.username || "") !== userRaw) continue;

      const rowDetailsRaw = String(row.details || "");
      const rowDetailsObj = parseDetails(rowDetailsRaw) || {};
      const rowOpId = String(rowDetailsObj.op_id || "").trim();
      if (opId && rowOpId && opId !== rowOpId) continue;

      used.add(j);
      const titleMatch = rowDetailsRaw.match(/title=(.+)/i);
      if (!titleRaw) {
        titleRaw = String(rowDetailsObj.title || (titleMatch ? titleMatch[1].trim() : "") || "").trim();
      }

      techRows.push({
        event: escapeHtml(rowEvent),
        time: escapeHtml(String(row.created_at || "")),
        status: escapeHtml(String(row.status || "-")),
        details: escapeHtml(
          rowDetailsObj && Object.keys(rowDetailsObj).length
            ? JSON.stringify(rowDetailsObj, null, 2)
            : rowDetailsRaw
        ),
      });
    }

    used.add(i);
    const finishPretty = Object.keys(finishDetailsObj).length
      ? escapeHtml(JSON.stringify(finishDetailsObj, null, 2))
      : "";
    const title = escapeHtml(titleRaw);
    const techHtml = techRows.map((row) => `
      <div class="ops-tech-row">
        <div><b>${row.event}</b> | <code>${row.time}</code> | <code>${row.status}</code></div>
        ${row.details ? `<pre class="ops-pre">${row.details}</pre>` : ""}
      </div>
    `).join("");

    cards.push(`
      <div class="ops-log-card mb-2 pb-2 border-bottom border-secondary-subtle">
        <div class="ops-log-head"><b>upload_finished</b> <span class="text-info">[${lvl}]</span></div>
        <div class="ops-log-grid">
          <div><span class="ops-label">Кто:</span> <code>${escapeHtml(userRaw)}</code></div>
          <div><span class="ops-label">Когда:</span> <code>${uploadedAt}</code></div>
          <div><span class="ops-label">Название:</span> ${title || "<span class='text-muted'>-</span>"}</div>
          <div><span class="ops-label">Ссылка:</span> ${videoUrl ? `<a href="${videoUrl}" target="_blank" rel="noopener">${videoUrl}</a>` : "<span class='text-muted'>-</span>"}</div>
          <div><span class="ops-label">Статус:</span> <code>${st}</code></div>
          ${publishAt ? `<div><span class="ops-label">Публикация:</span> <code>${publishAt}</code></div>` : ""}
        </div>
        <details class="ops-details mt-2">
          <summary>Подробности</summary>
          ${finishPretty ? `<pre class="ops-pre">${finishPretty}</pre>` : "<div class='text-muted small mt-2'>Корневых метаданных нет.</div>"}
          ${techHtml || "<div class='text-muted small mt-2'>Технических подпроцессов нет.</div>"}
        </details>
      </div>
    `);
  }

  for (let i = 0; i < items.length; i += 1) {
    if (used.has(i)) continue;
    const item = items[i];
    const eventRaw = String(item.event || "");
    if (eventRaw === "upload_started" || eventRaw === "youtube_upload_started") continue;
    const ts = escapeHtml(String(item.created_at || ""));
    const lvl = escapeHtml(String(item.level || "INFO"));
    const event = escapeHtml(eventRaw);
    const user = escapeHtml(String(item.username || "-"));
    const st = escapeHtml(String(item.status || "-"));
    const detailsRaw = String(item.details || "");
    const detailsObj = parseDetails(detailsRaw);
    const detailsPretty = detailsObj ? escapeHtml(JSON.stringify(detailsObj, null, 2)) : escapeHtml(detailsRaw);

    cards.push(`
      <div class="ops-log-card mb-2 pb-2 border-bottom border-secondary-subtle">
        <div><b>${event}</b> <span class="text-info">[${lvl}]</span></div>
        <div class="text-muted">${ts}</div>
        <div>user: <code>${user}</code> | status: <code>${st}</code></div>
        ${detailsRaw ? `<details class="ops-details mt-1"><summary>Подробности</summary><pre class="ops-pre">${detailsPretty}</pre></details>` : ""}
      </div>
    `);
  }

  opsLogsEl.innerHTML = cards.join("");
}

async function loadOpsLogs() {
  const res = await fetch("/api/ops_logs?limit=30");
  const parsed = await safeJson(res);
  if (!parsed.ok) {
    if (opsLogsEl) opsLogsEl.innerHTML = `<div class="text-danger">Не удалось загрузить логи</div>`;
    return;
  }
  renderOpsLogs(parsed.data.items || []);
}

regenHashtagsBtn?.addEventListener("click", async () => {
  if (uiBusy) return;
  try {
    const title = String(titleEl?.value || "").trim();
    if (!title) throw new Error("Заполните название видео");

    setStatus("Перегенерирую теги...");
    const fd = new FormData();
    fd.append("title", title);

    const res = await fetch("/api/gen_tags", { method: "POST", body: fd });
    const parsed = await safeJson(res);
    if (!parsed.ok) {
      throw new Error(parsed.data?.detail || parsed.raw || "Ошибка генерации тегов");
    }

    if (hashtagsEl) hashtagsEl.value = parsed.data.hashtags || "";
    setStatus("Теги обновлены ✅");
  } catch (e) {
    setStatus("Ошибка");
    showError("Ошибка: " + e.message);
  }
});

regenSeoBtn?.addEventListener("click", async () => {
  if (uiBusy) return;
  try {
    const title = String(titleEl?.value || "").trim();
    if (!title) throw new Error("Необходимо заполнить название видео");

    setStatus("Перегенерируется SEO...");
    const fd = new FormData();
    fd.append("title", title);

    const res = await fetch("/api/gen_tags", { method: "POST", body: fd });
    const parsed = await safeJson(res);
    if (!parsed.ok) {
      throw new Error(parsed.data?.detail || parsed.raw || "Ошибка генерации SEO");
    }

    if (seoEl) seoEl.value = parsed.data.seo_tags || "";
    setStatus("SEO обновлены ✅");
  } catch (e) {
    setStatus("Ошибка");
    showError("Ошибка: " + e.message);
  }
});

clearBtn?.addEventListener("click", () => {
  if (uiBusy) return;
  if (hashtagsEl) hashtagsEl.value = "";
  if (seoEl) seoEl.value = "";
  if (publishEl) publishEl.value = "";
  if (previewImg) previewImg.src = "";
  if (previewFilenameEl) previewFilenameEl.value = "";
  if (previewFileEl) previewFileEl.value = "";
  if (videoEl) videoEl.value = "";
  hideResult();
  setStatus("Поля очищены ✅");
});

fillBtn?.addEventListener("click", async () => {
  if (uiBusy) return;
  try {
    hideResult();
    if (previewImg) previewImg.classList.add("img-loading");

    const title = String(titleEl?.value || "").trim();
    if (!title) throw new Error("Необходимо заполнить название видео");

    const bpmValue = normalizeAndValidateBpm(bpmEl?.value || "");
    if (bpmEl) bpmEl.value = bpmValue;

    setStatus("Gemini + превью: работаю...");

    const fd = new FormData();
    fd.append("title", title);
    fd.append("purchase_link", String(purchaseLinkEl?.value || "").trim());
    fd.append("bpm", bpmValue);
    fd.append("key", keyEl?.value || "");

    const res = await fetch("/api/fill", { method: "POST", body: fd });
    const parsed = await safeJson(res);
    if (!parsed.ok) {
      throw new Error(parsed.data?.detail || parsed.raw || "Ошибка /api/fill");
    }

    const data = parsed.data || {};
    if (hashtagsEl) hashtagsEl.value = data.hashtags || "";
    if (seoEl) seoEl.value = data.seo_tags || "";

    let previewStatus = "";
    if (data.preview_url && previewImg) {
      previewImg.onload = () => previewImg.classList.remove("img-loading");
      previewImg.src = `${data.preview_url}?t=${Date.now()}`;
      if (previewFilenameEl) previewFilenameEl.value = data.preview_filename || "";
      previewStatus = " + превью обновлено";
    } else if (previewImg) {
      previewImg.classList.remove("img-loading");
    }

    await loadGallery();

    if (data.warning) {
      showSuccessHtml(`
        <div class="glitch-ai-warning">
          <b>AI_STATUS // SEMI_OFFLINE</b>
          ${escapeHtml(data.warning)}
          <small>> Подставлены стандартные теги и описание.<br>Проверьте их в ручную.</small>
        </div>
      `);
      setStatus("Готово (ИИ был ограничен)" + previewStatus);
    } else {
      setStatus("Готово ✅" + previewStatus);
    }
  } catch (e) {
    if (previewImg) previewImg.classList.remove("img-loading");
    setStatus("Ошибка");
    showError("Ошибка: " + e.message);
  }
});

refreshPreviewBtn?.addEventListener("click", async () => {
  if (uiBusy) return;
  try {
    hideResult();
    const title = String(titleEl?.value || "").trim();
    if (!title) throw new Error("Заполните название");

    if (previewFileEl) previewFileEl.value = "";
    if (localPreviewUrl) {
      URL.revokeObjectURL(localPreviewUrl);
      localPreviewUrl = null;
    }

    setStatus("Ищу другое превью...");
    const fd = new FormData();
    fd.append("title", title);

    const res = await fetch("/api/preview/refresh", { method: "POST", body: fd });
    const parsed = await safeJson(res);
    if (!parsed.ok) {
      throw new Error(parsed.data?.detail || parsed.raw || "Ошибка /api/preview/refresh");
    }

    const data = parsed.data || {};
    if (previewImg) previewImg.src = `${data.preview_url || ""}?t=${Date.now()}`;
    if (previewFilenameEl) previewFilenameEl.value = data.preview_filename || "";
    await loadGallery();
    setStatus("Новое превью ✅");
  } catch (e) {
    setStatus("Ошибка");
    showError("Ошибка: " + e.message);
  }
});

refreshGalleryBtn?.addEventListener("click", async () => {
  if (uiBusy) return;
  try {
    hideResult();
    setStatus("Обновляю галерею...");
    await loadGallery();
    setStatus("Галерея обновлена ✅");
  } catch (e) {
    setStatus("Ошибка");
    showError("Ошибка галереи: " + e.message);
  }
});

previewFileEl?.addEventListener("change", () => {
  const file = previewFileEl.files?.[0];
  if (!file || !previewImg) return;

  if (localPreviewUrl) {
    URL.revokeObjectURL(localPreviewUrl);
    localPreviewUrl = null;
  }

  localPreviewUrl = URL.createObjectURL(file);
  previewImg.src = localPreviewUrl;
  if (previewFilenameEl) previewFilenameEl.value = "";
  setStatus("Выбрано своё превью ✅");
});

function dateToIsoLocal(dateObj) {
  const year = dateObj.getFullYear();
  const month = String(dateObj.getMonth() + 1).padStart(2, "0");
  const day = String(dateObj.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function applyDutyDayClass(dayElem) {
  dayElem.classList.remove("duty-uploaded", "duty-missed");
  if (!dayElem?.dateObj) return;
  const iso = dateToIsoLocal(dayElem.dateObj);
  const state = calendarDutyStates.get(iso);
  if (state === "uploaded") dayElem.classList.add("duty-uploaded");
  if (state === "missed") dayElem.classList.add("duty-missed");
}

async function loadDutyCalendarStatus(fpInstance) {
  if (!fpInstance || typeof fpInstance.currentYear !== "number" || typeof fpInstance.currentMonth !== "number") return;
  const reqId = ++calendarDutyReqSeq;
  const year = fpInstance.currentYear;
  const month = fpInstance.currentMonth + 1;

  try {
    const res = await fetch(`/api/calendar_duty_status?year=${year}&month=${month}`);
    const parsed = await safeJson(res);
    if (!parsed.ok || !parsed.data) return;
    if (reqId !== calendarDutyReqSeq) return;

    calendarDutyStates = new Map(Object.entries(parsed.data.days || {}));
    fpInstance.redraw();
  } catch {
    // optional
  }
}

function initPublishPicker() {
  if (!publishEl || typeof flatpickr !== "function") return;

  flatpickr("#publish_dt", {
    locale: "ru",
    firstDayOfWeek: 1,
    enableTime: true,
    dateFormat: "Y-m-d H:i",
    time_24hr: true,
    minuteIncrement: 5,
    minDate: "today",
    onDayCreate(_, __, ___, dayElem) {
      applyDutyDayClass(dayElem);
    },
    onReady(selectedDates, dateStr, instance) {
      const hourInput = instance.timeContainer?.querySelector(".flatpickr-hour");
      const minuteInput = instance.timeContainer?.querySelector(".flatpickr-minute");

      const handleWheelScroll = (e, isHour) => {
        e.preventDefault();
        const date = instance.selectedDates[0] || new Date();
        let value = isHour ? date.getHours() : date.getMinutes();
        const delta = e.deltaY < 0 ? 1 : -1;

        if (isHour) {
          value += delta;
          if (value > 23) value = 0;
          if (value < 0) value = 23;
          date.setHours(value);
        } else {
          value += delta * 5;
          if (value > 55) value = 0;
          if (value < 0) value = 55;
          date.setMinutes(value);
        }

        instance.setDate(date, true);
      };

      hourInput?.addEventListener("wheel", (e) => handleWheelScroll(e, true));
      minuteInput?.addEventListener("wheel", (e) => handleWheelScroll(e, false));
      loadDutyCalendarStatus(instance);
    },
    onMonthChange(selectedDates, dateStr, instance) {
      loadDutyCalendarStatus(instance);
    },
    onYearChange(selectedDates, dateStr, instance) {
      loadDutyCalendarStatus(instance);
    },
  });
}

function formatDate(isoString) {
  try {
    return new Date(isoString).toLocaleString("ru-RU", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return isoString;
  }
}

uploadBtn?.addEventListener("click", () => {
  if (uiBusy) return;
  try {
    hideResult();

    const title = String(titleEl?.value || "").trim();
    if (!title) throw new Error("Заполните название");

    const hasLocalVideo = !!(videoEl?.files && videoEl.files.length > 0);
    const serverVideoFilename = String(serverVideoFilenameEl?.value || "").trim();
    if (!hasLocalVideo && !serverVideoFilename) {
      throw new Error("Выберите видео файл");
    }

    const bpmValue = normalizeAndValidateBpm(bpmEl?.value || "");
    if (bpmEl) bpmEl.value = bpmValue;

    setStatus("Загружаю видео на YouTube...");
    uploadProgressWrap?.classList.remove("d-none");
    if (uploadProgressBar) {
      uploadProgressBar.style.width = "0%";
      uploadProgressBar.textContent = "0%";
    }

    const fd = new FormData();
    fd.append("title", title);
    fd.append("purchase_link", String(purchaseLinkEl?.value || "").trim());
    fd.append("hashtags", hashtagsEl?.value || "");
    fd.append("seo_tags", seoEl?.value || "");
    fd.append("publish_dt_local", publishEl?.value || "");
    fd.append("bpm", bpmValue);
    fd.append("key", keyEl?.value || "");

    if (previewFileEl?.files && previewFileEl.files.length > 0) {
      fd.append("preview_file", previewFileEl.files[0]);
    } else {
      fd.append("preview_filename", previewFilenameEl?.value || "");
    }

    if (hasLocalVideo) {
      fd.append("video_file", videoEl.files[0]);
    }
    if (serverVideoFilename) {
      fd.append("server_video_filename", serverVideoFilename);
    }

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload", true);

    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const percent = Math.round((e.loaded / e.total) * 100);
      if (uploadProgressBar) {
        uploadProgressBar.style.width = `${percent}%`;
        uploadProgressBar.textContent = `${percent}%`;
      }
      setStatus(`Загружаю видео... ${percent}%`);
    };

    xhr.onload = () => {
      uploadProgressWrap?.classList.add("d-none");

      if (xhr.status < 200 || xhr.status >= 300) {
        setStatus("Ошибка");
        let message = xhr.responseText || "Ошибка /api/upload";
        try {
          const json = JSON.parse(xhr.responseText || "{}");
          message = json?.detail || message;
        } catch {
          // ignore
        }
        showError(message);
        return;
      }

      let data = {};
      try {
        data = JSON.parse(xhr.responseText || "{}");
      } catch {
        setStatus("Ошибка");
        showError("Ответ сервера не похож на JSON: " + String(xhr.responseText || "").slice(0, 300));
        return;
      }

      setStatus("Готово ✅");

      if (data.used_server_video) {
        clearGeneratedVideoSelection(true);
      }

      if (opsLogsEl) {
        loadOpsLogs().catch(() => {});
      }

      const publishText = data.publish_at ? formatDate(data.publish_at) : "Сразу после загрузки";
      const url = data.video_url || (data.video_id ? `https://youtu.be/${data.video_id}` : "");
      const playlists = Array.isArray(data.playlists) ? data.playlists : [];
      const playlistsHtml = playlists.length
        ? `<ul class="glitch-success-list">` + playlists.map((playlist) => {
            const isStr = typeof playlist === "string";
            const nameRaw = isStr ? playlist : (playlist?.name || playlist?.id || "");
            const idRaw = isStr ? "" : (playlist?.id || "");
            const linkRaw = isStr ? "" : (playlist?.url || (idRaw ? `https://www.youtube.com/playlist?list=${encodeURIComponent(idRaw)}` : ""));
            const name = escapeHtml(String(nameRaw || ""));
            return `<li>${linkRaw ? `<a href="${linkRaw}" target="_blank" rel="noreferrer">${name}</a>` : name}</li>`;
          }).join("") + `</ul>`
        : `<span class="text-muted">Нет</span>`;

      const warnings = Array.isArray(data.warnings) ? data.warnings : [];
      const warningsHtml = warnings.length
        ? `<div class="glitch-warning-panel mt-3">
             <b>SYSTEM_WARNINGS //</b>
             <ul class="mb-0 mt-1 glitch-success-list">${warnings.map((warning) => `<li>${escapeHtml(String(warning))}</li>`).join("")}</ul>
           </div>`
        : "";

      triggerGlitchToast();

      showSuccessHtml(`
        <div class="glitch-success-container">
          <div class="glitch-success-header mb-4">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="me-2">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
            SYSTEM // UPLOAD_COMPLETE
          </div>

          <div class="glitch-success-item"><b>VIDEO_ID:</b> <span class="text-white">${escapeHtml(String(data.video_id || "N/A"))}</span></div>
          <div class="glitch-success-item"><b>ПУБЛИКАЦИЯ:</b> <span class="text-white">${escapeHtml(publishText)}</span></div>
          ${url ? `
            <div class="glitch-success-item">
              <b>ССЫЛКА:</b>
              <a href="${url}" target="_blank" rel="noreferrer" class="glitch-success-link">${escapeHtml(url)}</a>
            </div>
          ` : ""}
          <div class="glitch-success-item mt-3">
            <b>ПЛЕЙЛИСТЫ:</b>
            ${playlistsHtml}
          </div>
          ${warningsHtml}
          <details class="glitch-details mt-4">
            <summary class="small">>> DECRYPT_RAW_DATA.JSON</summary>
            <pre class="tech-json p-2 mt-2 mb-0 small" style="white-space: pre-wrap;">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
          </details>
        </div>
      `);
    };

    xhr.send(fd);
  } catch (e) {
    uploadProgressWrap?.classList.add("d-none");
    setStatus("Ошибка");
    showError("Ошибка: " + (e?.message || String(e)));
  }
});

refreshOpsBtn?.addEventListener("click", async () => {
  try {
    await loadOpsLogs();
  } catch (e) {
    setStatus("Ошибка");
    showError("Ошибка логов: " + e.message);
  }
});

bpmEl?.addEventListener("input", () => {
  bpmEl.value = String(bpmEl.value || "").replace(/\D+/g, "").slice(0, 3);
});

document.addEventListener("DOMContentLoaded", () => {
  syncCreateVideoHref();
  loadGeneratedVideoSelection();
  loadGallery().catch(() => {});
  if (opsLogsEl) {
    loadOpsLogs().catch(() => {});
  }
  initPublishPicker();

  if (titleEl) {
    titleEl.addEventListener("input", syncCreateVideoHref);
  }

  clearServerVideoBtn?.addEventListener("click", () => {
    clearGeneratedVideoSelection(true);
    setStatus("Монтаж готов ✅");
  });

  videoEl?.addEventListener("change", () => {
    if (videoEl.files?.length) {
      clearGeneratedVideoSelection(true);
    }
  });

  if (previewImg) {
    previewImg.style.cursor = "zoom-in";
    previewImg.addEventListener("click", () => {
      if (previewImg.src && !previewImg.src.includes("data:image")) {
        openZoom(previewImg.src, "Текущее превью");
      }
    });
  }

  lightbox?.addEventListener("click", (e) => {
    if (e.target !== lightboxImg) {
      closeZoom();
    }
  });
});
