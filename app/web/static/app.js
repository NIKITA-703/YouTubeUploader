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
const resultBox = document.getElementById("resultBox");

// gallery
const galleryEl = document.getElementById("preview_gallery");
const refreshGalleryBtn = document.getElementById("refresh_gallery_btn");

function setStatus(msg) {
  if (statusEl) statusEl.textContent = msg || "";
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
    previewFilenameEl.value = name;
    previewImg.src = url + "?t=" + Date.now();
    setStatus("Выбрано превью ✅");

    // подсветка выбранной карточки (если есть CSS)
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
          <button type="button" class="btn btn-sm btn-primary w-100 mt-1">Выбрать</button>
        </div>
      </div>
    `;

    const card = col.querySelector(".preview-card");
    const btn = col.querySelector("button");
    const img = col.querySelector("img");

    // кнопка
    btn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      selectPreview(it.name, it.url);
    };

    // клик по карточке
    card.onclick = () => selectPreview(it.name, it.url);

    // клик по картинке (на всякий)
    img.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      selectPreview(it.name, it.url);
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
  try {
    hideResult();

    const title = (titleEl.value || "").trim();
    if (!title) throw new Error("Введите название");

    setStatus("Gemini + превью: работаю...");

    const fd = new FormData();
    fd.append("title", title);

    const res = await fetch("/api/fill", { method: "POST", body: fd });
    const parsed = await safeJson(res);

    if (!parsed.ok) {
      throw new Error(parsed.data?.detail || parsed.raw || "Ошибка /api/fill");
    }

    const data = parsed.data;
    hashtagsEl.value = data.hashtags || "";
    seoEl.value = data.seo_tags || "";

    previewImg.src = (data.preview_url || "") + "?t=" + Date.now();
    previewFilenameEl.value = data.preview_filename || "";

    await loadGallery();
    setStatus("Готово ✅");
  } catch (e) {
    setStatus("Ошибка");
    showError("Ошибка: " + e.message);
  }
});

refreshPreviewBtn?.addEventListener("click", async () => {
  try {
    hideResult();

    const title = (titleEl.value || "").trim();
    if (!title) throw new Error("Введите название");

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

uploadBtn?.addEventListener("click", async () => {
  try {
    hideResult();

    const title = (titleEl.value || "").trim();
    if (!title) throw new Error("Введите название");

    if (!videoEl.files || videoEl.files.length === 0) {
      throw new Error("Выберите видео файл");
    }

    setStatus("Загружаю на YouTube... Не закрывай страницу.");

    const fd = new FormData();
    fd.append("title", title);
    fd.append("hashtags", hashtagsEl.value || "");
    fd.append("seo_tags", seoEl.value || "");
    fd.append("publish_dt_local", publishEl.value || "");

    // превью: ручной файл > выбранное авто-превью
    if (previewFileEl.files && previewFileEl.files.length > 0) {
      fd.append("preview_file", previewFileEl.files[0]);
    } else {
      fd.append("preview_filename", previewFilenameEl.value || "");
    }

    fd.append("video_file", videoEl.files[0]);

    const res = await fetch("/api/upload", { method: "POST", body: fd });
    const parsed = await safeJson(res);

    if (!parsed.ok) {
      const detail = parsed.data?.detail || parsed.raw || "Ошибка /api/upload";
      throw new Error(detail);
    }

    const data = parsed.data || {};

    // --- красивый вывод ---
    const publishHtml = data.publish_at
      ? `<div><b>Публикация:</b> ${data.publish_at} (UTC)</div>`
      : `<div><b>Публикация:</b> без расписания</div>`;

    const playlists = Array.isArray(data.playlists) ? data.playlists : [];

    const playlistsHtml = playlists.length
      ? `<ul class="mb-0">` +
        playlists.map(p => {
          // ✅ поддержка и строк, и объекта
          const isStr = (typeof p === "string");
          const nameRaw = isStr ? p : (p?.name || p?.id || "");
          const urlRaw = isStr ? "" : (p?.url || (p?.id ? `https://www.youtube.com/playlist?list=${encodeURIComponent(p.id)}` : ""));

          const name = escapeHtml(String(nameRaw || ""));
          const url = String(urlRaw || "");

          return `<li>${url ? `<a href="${url}" target="_blank" rel="noreferrer">${name}</a>` : name}</li>`;
        }).join("") +
        `</ul>`
      : `<div>—</div>`;

    const url = data.video_url || (data.video_id ? `https://www.youtube.com/watch?v=${data.video_id}` : "");
    const idHtml = data.video_id ? `<div><b>Video ID:</b> ${escapeHtml(data.video_id)}</div>` : "";

    const warnings = Array.isArray(data.warnings) ? data.warnings : [];
    const warningsHtml = warnings.length
      ? `<div class="alert alert-warning mt-3 mb-0"><b>Предупреждения:</b><ul class="mb-0">${warnings.map(w => `<li>${escapeHtml(w)}</li>`).join("")}</ul></div>`
      : "";

    showSuccessHtml(`
      <div class="fw-bold mb-2">${escapeHtml(data.message || "Видео загружено ✅")}</div>
      ${idHtml}
      ${publishHtml}
      ${url ? `<div><b>Ссылка:</b> <a href="${url}" target="_blank" rel="noreferrer">${url}</a></div>` : ""}
      <div class="mt-2"><b>Плейлисты:</b>${playlistsHtml}</div>

      ${warningsHtml}

      <details class="mt-3">
        <summary class="small text-muted">Тех. детали</summary>
        <pre class="bg-light border rounded p-2 mt-2 mb-0 small" style="white-space: pre-wrap;">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
      </details>
    `);

    setStatus("Готово ✅");
  } catch (e) {
    setStatus("Ошибка");
    showError("Ошибка: " + (e?.message || String(e)));
  }
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
});
