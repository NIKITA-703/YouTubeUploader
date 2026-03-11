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

const statusEl = document.getElementById("status");
const statusOverlayEl = document.getElementById("status_overlay");
const statusOverlayTextEl = document.getElementById("status_overlay_text");
const resultBox = document.getElementById("resultBox");

const uploadProgressWrap = document.getElementById("uploadProgressWrap");
const uploadProgressBar = document.getElementById("uploadProgressBar");

const regenHashtagsBtn = document.getElementById("regen_hashtags_btn");
const regenSeoBtn = document.getElementById("regen_seo_btn");

const purchaseLinkEl = document.getElementById("purchase_link");

const bpmEl = document.getElementById("bpm");
const keyEl = document.getElementById("key");

// gallery
const galleryEl = document.getElementById("preview_gallery");
const refreshGalleryBtn = document.getElementById("refresh_gallery_btn");
const opsLogsEl = document.getElementById("ops_logs");
const refreshOpsBtn = document.getElementById("refresh_ops_btn");

const successSound = new Audio('/static/sounds/success.mp3');
successSound.volume = 0.5; // Уровень громкости (от 0 до 1)

const lightbox = document.getElementById("glitch-lightbox");
const lightboxImg = document.getElementById("lightbox_img");
const lightboxCaption = document.getElementById("lightbox_caption");

let statusOverlayHideTimer = null;
let _uiBusy = false;

const _backendActionButtons = [
  fillBtn,
  regenHashtagsBtn,
  regenSeoBtn,
  refreshPreviewBtn,
  refreshGalleryBtn,
  uploadBtn,
].filter(Boolean);

function _setBackendButtonsDisabled(disabled) {
  for (const btn of _backendActionButtons) {
    btn.disabled = !!disabled;
  }
}

function setStatus(msg) {
  const text = String(msg || "").trim();
  if (statusEl) statusEl.textContent = text;
  if (!statusOverlayEl || !statusOverlayTextEl) return;

  if (statusOverlayHideTimer) {
    clearTimeout(statusOverlayHideTimer);
    statusOverlayHideTimer = null;
  }

  if (!text) {
    _uiBusy = false;
    _setBackendButtonsDisabled(false);
    statusOverlayEl.classList.remove("is-visible", "is-error", "is-success", "is-busy");
    return;
  }

  const lower = text.toLowerCase();
  const isError = /(ошибка|error)/i.test(lower);
  const isSuccess =
    text.includes("✅") ||
    /(готово|обновлен|обновлена|обновлены|выбрано|очищено|успех|success)/i.test(lower);
  const isBusy = !isError && !isSuccess;
  _uiBusy = isBusy;
  _setBackendButtonsDisabled(isBusy);

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
  resultBox.classList.remove("alert-success", "alert-danger");
  resultBox.innerHTML = "";
}

function showError(msg) {
  if (!resultBox) return;
  resultBox.classList.remove("d-none");
  resultBox.classList.add("alert", "alert-danger");
  resultBox.classList.remove("alert-success");
  resultBox.textContent = msg;
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
  } catch (_) {
    return { ok: res.ok, status: res.status, data: null, raw: text };
  }
}

function triggerGlitchToast() {
  const toast = document.getElementById('glitch-toast-container');

  setTimeout(() => {
      successSound.currentTime = 0;
      successSound.play().catch(err => {
          // Браузеры иногда блокируют звук до первого клика пользователя
          console.log("Звук заблокирован до взаимодействия с сайтом:", err);
      });
  }, 100);

  // Показываем
  toast.classList.add('show');

  // Убираем через 4 секунды
  setTimeout(() => {
    toast.classList.remove('show');
  }, 4000);
}



/* =========================
   GALLERY
========================= */

function renderGallery(items) {
  if (!galleryEl) return;
  galleryEl.innerHTML = "";


  if (!items || items.length === 0) {
    galleryEl.innerHTML = `<div class="text-muted small">Пока нет превью в папке.</div>`;
    return;
  }

  function selectPreview(name, url) {

    // 1) если ранее было выбрано локальное превью-файлом — сбросим режим файла
      if (previewFileEl) previewFileEl.value = "";

      // 2) если был blob url от локального файла — освободим его
      if (_localPreviewUrl) {
        URL.revokeObjectURL(_localPreviewUrl);
        _localPreviewUrl = null;
      }

      // 3) включаем режим "из галереи"
      previewFilenameEl.value = name;
      previewImg.src = url + "?t=" + Date.now();
      setStatus("Выбрано превью ✅");

      // подсветка выбранной карточки
      const cards = galleryEl.querySelectorAll(".preview-card");
      for (const c of cards) c.classList.remove("selected");
      const active = galleryEl.querySelector(`.preview-card[data-name="${CSS.escape(name)}"]`);
      if (active) active.classList.add("selected");
    }

  for (const it of items) {
    const col = document.createElement("div");
    col.className = "col-6 col-md-4";

    col.innerHTML = `
      <div class="card h-100 shadow-sm preview-card" data-name="${it.name}" style="cursor:pointer;">
        <img src="${it.url}?t=${Date.now()}" class="card-img-top preview-img" alt="${it.name}">
        <div class="card-body p-2">
          <div class="small text-truncate" title="${it.name}">${it.name}</div>
          <button type="button"
                  class="btn btn-sm btn-primary w-100 mt-1 glitch-primary-like-login"
                  data-text="ВЫБРАТЬ">
            <span class="btn-text">Выбрать</span>
          </button>
        </div>
      </div>
    `;

    const card = col.querySelector(".preview-card");
    const btn = col.querySelector("button");
    const img = col.querySelector("img");

    // 1. КНОПКА — по-прежнему ВЫБИРАЕТ фотку для загрузки
    btn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation(); // Чтобы клик не ушёл на карточку
      selectPreview(it.name, it.url);
    };

    // 2. КАРТИНКА — теперь УВЕЛИЧИВАЕТ (Zoom)
    img.style.cursor = "zoom-in";
    img.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation(); // Чтобы клик не ушёл на карточку и не выбрал фото
      openZoom(it.url, it.name); // Вызываем функцию увеличения
    };

    // 3. КАРТОЧКА (клик по названию или фону) — ВЫБИРАЕТ фотку
    card.onclick = (e) => {
      // Проверяем, что кликнули не по картинке (картинка теперь сама по себе)
      if (e.target !== img) {
        selectPreview(it.name, it.url);
      }
    };

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
    opsLogsEl.innerHTML = `<div class="text-muted">No logs yet.</div>`;
    return;
  }

  const parseDetails = (raw) => {
    const text = String(raw || "").trim();
    if (!text) return null;
    if (!(text.startsWith("{") || text.startsWith("["))) return null;
    try {
      return JSON.parse(text);
    } catch (_) {
      return null;
    }
  };

  const pickVideoUrl = (detailsObj, detailsText) => {
    if (detailsObj?.video_url) return String(detailsObj.video_url);
    if (detailsObj?.video_id) return `https://youtu.be/${detailsObj.video_id}`;
    const m = String(detailsText || "").match(/video_id=([A-Za-z0-9_-]+)/);
    if (m) return `https://youtu.be/${m[1]}`;
    return "";
  };

  const used = new Set();
  const cards = [];

  for (let i = 0; i < items.length; i++) {
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
    for (let j = i + 1; j < items.length; j++) {
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
        details: escapeHtml(rowDetailsObj && Object.keys(rowDetailsObj).length ? JSON.stringify(rowDetailsObj, null, 2) : rowDetailsRaw),
      });
    }

    used.add(i);
    const finishPretty = Object.keys(finishDetailsObj).length
      ? escapeHtml(JSON.stringify(finishDetailsObj, null, 2))
      : "";
    const title = escapeHtml(titleRaw);
    const techHtml = techRows.map((r) => `
      <div class="ops-tech-row">
        <div><b>${r.event}</b> | <code>${r.time}</code> | <code>${r.status}</code></div>
        ${r.details ? `<pre class="ops-pre">${r.details}</pre>` : ""}
      </div>
    `).join("");

    cards.push(`
      <div class="ops-log-card mb-2 pb-2 border-bottom border-secondary-subtle">
        <div class="ops-log-head"><b>upload_finished</b> <span class="text-info">[${lvl}]</span></div>
        <div class="ops-log-grid">
          <div><span class="ops-label">Who:</span> <code>${escapeHtml(userRaw)}</code></div>
          <div><span class="ops-label">When:</span> <code>${uploadedAt}</code></div>
          <div><span class="ops-label">Title:</span> ${title || "<span class='text-muted'>-</span>"}</div>
          <div><span class="ops-label">Link:</span> ${videoUrl ? `<a href="${videoUrl}" target="_blank" rel="noopener">${videoUrl}</a>` : "<span class='text-muted'>-</span>"}</div>
          <div><span class="ops-label">Status:</span> <code>${st}</code></div>
          ${publishAt ? `<div><span class="ops-label">Schedule:</span> <code>${publishAt}</code></div>` : ""}
        </div>
        <details class="ops-details mt-2">
          <summary>Details</summary>
          ${finishPretty ? `<pre class="ops-pre">${finishPretty}</pre>` : "<div class='text-muted small mt-2'>No root metadata in upload_finished.</div>"}
          ${techHtml || "<div class='text-muted small mt-2'>No technical sub-events.</div>"}
        </details>
      </div>
    `);
  }

  for (let i = 0; i < items.length; i++) {
    if (used.has(i)) continue;
    const it = items[i];
    const evRaw = String(it.event || "");
    if (evRaw === "upload_started" || evRaw === "youtube_upload_started") continue;
    const ts = escapeHtml(String(it.created_at || ""));
    const lvl = escapeHtml(String(it.level || "INFO"));
    const ev = escapeHtml(evRaw);
    const user = escapeHtml(String(it.username || "-"));
    const st = escapeHtml(String(it.status || "-"));
    const detailsRaw = String(it.details || "");
    const detailsObj = parseDetails(detailsRaw);
    const det = escapeHtml(detailsRaw);
    const detailsPretty = detailsObj ? escapeHtml(JSON.stringify(detailsObj, null, 2)) : det;

    cards.push(`
      <div class="ops-log-card mb-2 pb-2 border-bottom border-secondary-subtle">
        <div><b>${ev}</b> <span class="text-info">[${lvl}]</span></div>
        <div class="text-muted">${ts}</div>
        <div>user: <code>${user}</code> | status: <code>${st}</code></div>
        ${det ? `<details class="ops-details mt-1"><summary>Details</summary><pre class="ops-pre">${detailsPretty}</pre></details>` : ""}
      </div>
    `);
  }

  opsLogsEl.innerHTML = cards.join("");
}

async function loadOpsLogs() {
  const res = await fetch("/api/ops_logs?limit=30");
  const parsed = await safeJson(res);
  if (!parsed.ok) {
    if (opsLogsEl) opsLogsEl.innerHTML = `<div class="text-danger">Ошибка загрузки логов</div>`;
    return;
  }
  renderOpsLogs(parsed.data.items || []);
}

regenHashtagsBtn?.addEventListener("click", async () => {
  if (_uiBusy) return;
  try {
    const title = (titleEl.value || "").trim();
    if (!title) throw new Error("Введите название видео");

    setStatus("Перегенерирую теги...");

    const fd = new FormData();
    fd.append("title", title);

    const res = await fetch("/api/gen_tags", {
      method: "POST",
      body: fd
    });

    const parsed = await safeJson(res);
    if (!parsed.ok) {
      throw new Error(parsed.data?.detail || parsed.raw || "Ошибка генерации тегов");
    }

    hashtagsEl.value = parsed.data.hashtags || "";
    setStatus("Теги обновлены ✅");
  } catch (e) {
    setStatus("Ошибка");
    showError("Ошибка: " + e.message);
  }
});

function openZoom(src, caption) {
  if (!lightbox || !lightboxImg) return;

  // Очищаем старый src, чтобы не было "призрака"
  lightboxImg.src = "";

  lightbox.style.display = "block";
  lightboxImg.src = src;
  lightboxCaption.innerHTML = caption || "PREVIEW_ENLARGED";
  document.body.style.overflow = "hidden";
}

// Закрытие при клике на крестик или на пустую область
lightbox.onclick = function(e) {
  if (e.target !== lightboxImg) {
    lightbox.style.display = "none";
    document.body.style.overflow = "auto";
  }
};

const mainPreviewImg = document.getElementById("preview_img");
mainPreviewImg.style.cursor = "zoom-in";
mainPreviewImg.onclick = () => {
  if (mainPreviewImg.src && !mainPreviewImg.src.includes("data:image")) {
     openZoom(mainPreviewImg.src, "CURRENT_PREVIEW");
  }
};

regenSeoBtn?.addEventListener("click", async () => {
  if (_uiBusy) return;
  try {
    const title = (titleEl.value || "").trim();
    if (!title) throw new Error("Введите название видео");

    setStatus("Перегенерирую SEO теги...");

    const fd = new FormData();
    fd.append("title", title);

    const res = await fetch("/api/gen_tags", {
      method: "POST",
      body: fd
    });

    const parsed = await safeJson(res);
    if (!parsed.ok) {
      throw new Error(parsed.data?.detail || parsed.raw || "Ошибка генерации SEO");
    }

    seoEl.value = parsed.data.seo_tags || "";
    setStatus("SEO теги обновлены ✅");
  } catch (e) {
    setStatus("Ошибка");
    showError("Ошибка: " + e.message);
  }
});


/* =========================
   BUTTONS
========================= */

clearBtn?.addEventListener("click", () => {
  hashtagsEl.value = "";
  seoEl.value = "";
  publishEl.value = "";
  previewImg.src = "";
  previewFilenameEl.value = "";
  previewFileEl.value = "";
  if (videoEl) videoEl.value = "";
  hideResult();
  setStatus("Очищено");
});

fillBtn?.addEventListener("click", async () => {
  if (_uiBusy) return;
  try {
    // Очищаем прошлые результаты и сбрасываем цвет статуса
    hideResult();
    if (statusEl) statusEl.style.color = "";

     previewImg.classList.add("img-loading");

    const title = (titleEl.value || "").trim();
    if (!title) {
        previewImg.classList.remove("img-loading"); // Возвращаем если ошибка
        throw new Error("Введите название");
    }

    const bpmValue = normalizeAndValidateBpm(bpmEl?.value || "");
    if (bpmEl) bpmEl.value = bpmValue;

    setStatus("Gemini + превью: работаю...");

    const fd = new FormData();
    fd.append("title", title);
    fd.append("purchase_link", (purchaseLinkEl.value || "").trim());
    fd.append("bpm", bpmValue);
    fd.append("key", keyEl.value);

    const res = await fetch("/api/fill", { method: "POST", body: fd });
    const parsed = await safeJson(res);

    if (!parsed.ok) {
      previewImg.classList.remove("img-loading"); // Возвращаем если ошибка
      throw new Error(parsed.data?.detail || parsed.raw || "Ошибка /api/fill");
    }

    const data = parsed.data;
    hashtagsEl.value = data.hashtags || "";
    seoEl.value = data.seo_tags || "";

    // Обновляем фото
    let previewStatus = "";
    if (data.preview_url) {
      // 2. Устанавливаем обработчик: когда НОВАЯ картинка загрузится — ВКЛЮЧАЕМ её
      previewImg.onload = () => {
          previewImg.classList.remove("img-loading"); // <-- ФИКС
      };

      previewImg.src = data.preview_url + "?t=" + Date.now();
      previewFilenameEl.value = data.preview_filename || "";
      previewStatus = " + Превью найдено";
    } else {
      // Если картинки нет — возвращаем видимость (для пустой заглушки)
      previewImg.classList.remove("img-loading");
    }

    await loadGallery();

    if (data.warning) {
      resultBox.innerHTML = `
        <div class="glitch-ai-warning">
          <b>AI_STATUS // SEMI_OFFLINE</b>
          ${data.warning}
          <small>> Поля заполнены стандартными тегами. <br> Проверьте их вручную.</small>
        </div>
      `;
      resultBox.classList.remove("d-none");
      setStatus("⚠️ Готово (есть замечания)" + previewStatus);
    } else {
      setStatus("Готово ✅" + previewStatus);
    }

  } catch (e) {
    previewImg.classList.remove("img-loading"); // Возвращаем видимость при любой ошибке
    setStatus("Ошибка");
    showError("Ошибка: " + e.message);
  }
});

refreshPreviewBtn?.addEventListener("click", async () => {
  if (_uiBusy) return;
  try {
    hideResult();

    const title = (titleEl.value || "").trim();
    if (!title) throw new Error("Введите название");

    if (previewFileEl) previewFileEl.value = "";
    if (_localPreviewUrl) {
      URL.revokeObjectURL(_localPreviewUrl);
      _localPreviewUrl = null;
    }

    setStatus("Ищу другое превью...");

    const fd = new FormData();
    fd.append("title", title);

    const res = await fetch("/api/preview/refresh", { method: "POST", body: fd });
    const parsed = await safeJson(res);

    if (!parsed.ok) {
      throw new Error(parsed.data?.detail || parsed.raw || "Ошибка /api/preview/refresh");
    }

    const data = parsed.data;
    previewImg.src = (data.preview_url || "") + "?t=" + Date.now();
    previewFilenameEl.value = data.preview_filename || "";

    await loadGallery();
    setStatus("Новое превью ✅");
  } catch (e) {
    setStatus("Ошибка");
    showError("Ошибка: " + e.message);
  }
});

refreshGalleryBtn?.addEventListener("click", async () => {
  if (_uiBusy) return;
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


let _localPreviewUrl = null;

previewFileEl?.addEventListener("change", () => {
  const f = previewFileEl.files?.[0];
  if (!f) return;

  // освободим прошлый blob url (если был)
  if (_localPreviewUrl) {
    URL.revokeObjectURL(_localPreviewUrl);
    _localPreviewUrl = null;
  }

  // покажем выбранную картинку в окне превью
  _localPreviewUrl = URL.createObjectURL(f);
  previewImg.src = _localPreviewUrl;

  // чтобы backend не взял старый preview_filename
  if (previewFilenameEl) previewFilenameEl.value = "";

  setStatus("Выбрано своё превью ✅");
});

function formatDate(isoString) {
  if (!isoString) return "IMMEDIATE_RELEASE";
  const d = new Date(isoString);
  if (isNaN(d.getTime())) return isoString;
  const pad = (n) => n.toString().padStart(2, '0');
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

let _calendarDutyStates = new Map();
let _calendarDutyReqSeq = 0;

function _dateToIsoLocal(dateObj) {
  const y = dateObj.getFullYear();
  const m = String(dateObj.getMonth() + 1).padStart(2, "0");
  const d = String(dateObj.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function _applyDutyDayClass(dayElem) {
  dayElem.classList.remove("duty-uploaded", "duty-missed");
  if (!dayElem?.dateObj) return;
  const iso = _dateToIsoLocal(dayElem.dateObj);
  const state = _calendarDutyStates.get(iso);
  if (state === "uploaded") dayElem.classList.add("duty-uploaded");
  if (state === "missed") dayElem.classList.add("duty-missed");
}

async function _loadDutyCalendarStatus(fpInstance) {
  if (!fpInstance || typeof fpInstance.currentYear !== "number" || typeof fpInstance.currentMonth !== "number") return;
  const reqId = ++_calendarDutyReqSeq;
  const year = fpInstance.currentYear;
  const month = fpInstance.currentMonth + 1;

  try {
    const res = await fetch(`/api/calendar_duty_status?year=${year}&month=${month}`);
    const parsed = await safeJson(res);
    if (!parsed.ok || !parsed.data) return;
    if (reqId !== _calendarDutyReqSeq) return;

    _calendarDutyStates = new Map(Object.entries(parsed.data.days || {}));
    fpInstance.redraw();
  } catch (_) {
    // Calendar highlighting is optional; ignore network errors.
  }
}

document.addEventListener("DOMContentLoaded", () => {
  flatpickr("#publish_dt", {
    locale: "ru",               // Подключаем русский язык
    firstDayOfWeek: 1,          // Пн - первый день недели
    enableTime: true,
    dateFormat: "Y-m-d H:i",
    time_24hr: true,
    minuteIncrement: 5,
    minDate: "today",
    onDayCreate: function(_, __, ___, dayElem) {
      _applyDutyDayClass(dayElem);
    },

    onReady: function(selectedDates, dateStr, instance) {
      const hourInput = instance.timeContainer.querySelector(".flatpickr-hour");
      const minuteInput = instance.timeContainer.querySelector(".flatpickr-minute");

      const handleWheelScroll = (e, input, isHour) => {
        e.preventDefault();

        // Берем уже выбранную дату или текущую как базу
        let date = instance.selectedDates[0] || new Date();
        let val = isHour ? date.getHours() : date.getMinutes();
        const delta = e.deltaY < 0 ? 1 : -1;

        if (isHour) {
          val += delta;
          if (val > 23) val = 0;
          if (val < 0) val = 23;
          date.setHours(val);
        } else {
          // Шаг 5 минут
          val += (delta * 5);
          if (val > 55) val = 0;
          if (val < 0) val = 55;
          date.setMinutes(val);
        }

        // Устанавливаем обновленную дату обратно в календарь
        instance.setDate(date, true);
      };

      if (hourInput) hourInput.addEventListener("wheel", (e) => handleWheelScroll(e, hourInput, true));
      if (minuteInput) minuteInput.addEventListener("wheel", (e) => handleWheelScroll(e, minuteInput, false));

      _loadDutyCalendarStatus(instance);
    },

    onMonthChange: function(selectedDates, dateStr, instance) {
      _loadDutyCalendarStatus(instance);
    },

    onYearChange: function(selectedDates, dateStr, instance) {
      _loadDutyCalendarStatus(instance);
    }
  });
});

uploadBtn?.addEventListener("click", () => {
  if (_uiBusy) return;
  try {
    hideResult();

    const title = (titleEl.value || "").trim();
    if (!title) throw new Error("Введите название");

    if (!videoEl.files || videoEl.files.length === 0) {
      throw new Error("Выберите видео файл");
    }
    const bpmValue = normalizeAndValidateBpm(bpmEl?.value || "");
    if (bpmEl) bpmEl.value = bpmValue;

    setStatus("Загружаю видео на сервер...");
    uploadProgressWrap?.classList.remove("d-none");

    // reset bar
    if (uploadProgressBar) {
      uploadProgressBar.style.width = "0%";
      uploadProgressBar.textContent = "0%";
    }

    const fd = new FormData();
    fd.append("title", title);
    fd.append("purchase_link", (purchaseLinkEl.value || "").trim());
    fd.append("hashtags", hashtagsEl?.value || "");
    fd.append("seo_tags", seoEl?.value || "");
    fd.append("publish_dt_local", publishEl?.value || "");
    fd.append("bpm", bpmValue);
    fd.append("key", keyEl.value);

    // превью
    if (previewFileEl?.files && previewFileEl.files.length > 0) {
      fd.append("preview_file", previewFileEl.files[0]);
    } else {
      fd.append("preview_filename", previewFilenameEl?.value || "");
    }

    fd.append("video_file", videoEl.files[0]);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload", true);

    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const percent = Math.round((e.loaded / e.total) * 100);

      if (uploadProgressBar) {
        uploadProgressBar.style.width = percent + "%";
        uploadProgressBar.textContent = percent + "%"; // Текст теперь будет черным на голубом
      }
      setStatus(`Загружаю видео… ${percent}%`);
    };

    xhr.onload = () => {
      uploadProgressWrap?.classList.add("d-none");

      // если сервер вернул ошибку — покажем текст как есть
      if (xhr.status < 200 || xhr.status >= 300) {
        setStatus("Ошибка");

        // иногда FastAPI возвращает JSON {"detail": "..."} — попробуем красиво
        let msg = xhr.responseText || "Ошибка /api/upload";
        try {
          const j = JSON.parse(xhr.responseText || "{}");
          msg = j?.detail || msg;
        } catch (_) {}

        showError(msg);
        return;
      }

      // безопасный JSON.parse
      let data = {};
      try {
        data = JSON.parse(xhr.responseText || "{}");
      } catch (e) {
        setStatus("Ошибка");
        showError("Ответ сервера не JSON: " + (xhr.responseText || "").slice(0, 300));
        return;
      }

      // финальный статус
      setStatus("Готово ✅");
      if (opsLogsEl) {
        loadOpsLogs().catch(() => {});
      }

      // --- красивый вывод ---
      const publishText = data.publish_at
      ? formatDate(data.publish_at)
      : "IMMEDIATE_RELEASE (БЕЗ РАСПИСАНИЯ)";

        // 2. Формируем ссылку (исправил твой url_id)
        const url = data.video_url || (data.video_id ? `https://youtu.be/${data.video_id}` : "");

        // 3. Плейлисты: теперь используем наш glitch-success-list
        const playlists = Array.isArray(data.playlists) ? data.playlists : [];
        const playlistsHtml = playlists.length
          ? `<ul class="glitch-success-list">` +
            playlists.map((p) => {
              const isStr = typeof p === "string";
              const nameRaw = isStr ? p : (p?.name || p?.id || "");
              const idRaw = isStr ? "" : (p?.id || "");
              const urlRaw = isStr
                ? ""
                : (p?.url || (idRaw ? `https://www.youtube.com/playlist?list=${encodeURIComponent(idRaw)}` : ""));

          const name = escapeHtml(String(nameRaw || ""));
          const link = String(urlRaw || "");

          return `<li>${link ? `<a href="${link}" target="_blank" rel="noreferrer">${name}</a>` : name}</li>`;
        }).join("") +
        `</ul>`
      : `<span class="text-muted">NONE</span>`;

    // 4. Предупреждения: используем glitch-warning-panel
    const warnings = Array.isArray(data.warnings) ? data.warnings : [];
    const warningsHtml = warnings.length
      ? `<div class="glitch-warning-panel mt-3">
           <b>SYSTEM_WARNINGS //</b>
           <ul class="mb-0 mt-1 glitch-success-list">${warnings.map(w => `<li>${escapeHtml(String(w))}</li>`).join("")}</ul>
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

      <div class="glitch-success-item"><b>SCHEDULE:</b> <span class="text-white">${publishText}</span></div>

       ${url ? `
          <div class="glitch-success-item">
            <b>ACCESS_URL:</b>
            <a href="${url}" target="_blank" rel="noreferrer" class="glitch-success-link">${escapeHtml(url)}</a>
          </div>` : ""
       }

    <div class="glitch-success-item mt-3">
      <b>TARGET_PLAYLISTS:</b>
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
    showError("Ошибка логов: " + e.message);
  }
});

bpmEl?.addEventListener("input", () => {
  const digitsOnly = (bpmEl.value || "").replace(/\D+/g, "").slice(0, 3);
  bpmEl.value = digitsOnly;
});

// маленький helper чтобы не ломать HTML (и не ловить XSS даже локально)
function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

/* =========================
   INIT
========================= */

window.addEventListener("DOMContentLoaded", () => {
  loadGallery().catch(() => {});
  if (opsLogsEl) {
    loadOpsLogs().catch(() => {});
  }
});

// =========================
// THEME TOGGLE (Bootstrap 5.3 data-bs-theme)
// =========================
(function initThemeToggle() {
  const toggle = document.getElementById("themeToggle");
  const root = document.documentElement; // <html>

  function applyTheme(theme) {
    root.setAttribute("data-bs-theme", theme);
    try { localStorage.setItem("theme", theme); } catch (_) {}
    if (toggle) toggle.checked = (theme === "light"); // checked = light (как на твоём скрине)
  }

  // default = dark (как ты хочешь)
  let saved = null;
  try { saved = localStorage.getItem("theme"); } catch (_) {}
  const theme = (saved === "light" || saved === "dark") ? saved : "dark";
  applyTheme(theme);

  if (toggle) {
    toggle.addEventListener("change", () => {
      // checked => light, unchecked => dark
      applyTheme(toggle.checked ? "light" : "dark");
    });
  }
})();
