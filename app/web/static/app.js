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
const resultEl = document.getElementById("result");
const historyEl = document.getElementById("preview_history");

// gallery
const galleryEl = document.getElementById("preview_gallery");
const refreshGalleryBtn = document.getElementById("refresh_gallery_btn");

function setStatus(msg) {
  statusEl.textContent = msg || "";
}

function setResult(obj) {
  resultEl.textContent = obj ? JSON.stringify(obj, null, 2) : "";
}

function addHistory(url) {
  if (!url) return;
  const a = document.createElement("a");
  a.href = url;
  a.textContent = url;
  a.target = "_blank";
  a.rel = "noreferrer";
  historyEl.prepend(a);
}

async function safeJson(res) {
  const text = await res.text();
  try { return { ok: res.ok, status: res.status, data: JSON.parse(text), raw: text }; }
  catch (_) { return { ok: res.ok, status: res.status, data: null, raw: text }; }
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

  for (const it of items) {
    const col = document.createElement("div");
    col.className = "col-6 col-md-4";

    col.innerHTML = `
      <div class="card h-100 shadow-sm">
        <img src="${it.url}?t=${Date.now()}" class="card-img-top" style="height:120px; object-fit:cover;">
        <div class="card-body p-2">
          <button type="button" class="btn btn-primary btn-sm w-100">Выбрать</button>
        </div>
      </div>
    `;

    col.querySelector("button").addEventListener("click", () => {
      previewFilenameEl.value = it.name;
      previewImg.src = it.url + "?t=" + Date.now();
      setStatus("Выбрано превью из галереи ✅");
      addHistory(it.url);
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

/* =========================
   BUTTONS
========================= */

clearBtn.addEventListener("click", () => {
  hashtagsEl.value = "";
  seoEl.value = "";
  publishEl.value = "";
  previewImg.src = "";
  previewFilenameEl.value = "";
  previewFileEl.value = "";
  if (videoEl) videoEl.value = "";
  setStatus("Очищено");
  setResult(null);
});

fillBtn.addEventListener("click", async () => {
  const title = (titleEl.value || "").trim();
  if (!title) {
    setStatus("Введите название");
    return;
  }

  setStatus("Gemini + превью: работаю...");
  setResult(null);

  const fd = new FormData();
  fd.append("title", title);

  const res = await fetch("/api/fill", { method: "POST", body: fd });
  const parsed = await safeJson(res);

  if (!parsed.ok) {
    setStatus("Ошибка fill: " + (parsed.data?.detail || parsed.raw));
    return;
  }

  const data = parsed.data;
  hashtagsEl.value = data.hashtags || "";
  seoEl.value = data.seo_tags || "";

  previewImg.src = (data.preview_url || "") + "?t=" + Date.now();
  previewFilenameEl.value = data.preview_filename || "";

  if (data.preview_url) addHistory(data.preview_url);

  // обновим галерею (чтобы новая картинка точно появилась)
  await loadGallery();

  setStatus("Готово ✅");
});

refreshPreviewBtn.addEventListener("click", async () => {
  const title = (titleEl.value || "").trim();
  if (!title) {
    setStatus("Введите название");
    return;
  }

  setStatus("Ищу другое превью...");
  setResult(null);

  const fd = new FormData();
  fd.append("title", title);

  const res = await fetch("/api/preview/refresh", { method: "POST", body: fd });
  const parsed = await safeJson(res);

  if (!parsed.ok) {
    setStatus("Ошибка refresh: " + (parsed.data?.detail || parsed.raw));
    return;
  }

  const data = parsed.data;
  previewImg.src = (data.preview_url || "") + "?t=" + Date.now();
  previewFilenameEl.value = data.preview_filename || "";

  if (data.preview_url) addHistory(data.preview_url);

  // обновим галерею
  await loadGallery();

  setStatus("Новое превью ✅");
});

refreshGalleryBtn.addEventListener("click", async () => {
  setStatus("Обновляю галерею...");
  await loadGallery();
  setStatus("Галерея обновлена ✅");
});

uploadBtn.addEventListener("click", async () => {
  const title = (titleEl.value || "").trim();
  if (!title) {
    setStatus("Введите название");
    return;
  }

  if (!videoEl.files || videoEl.files.length === 0) {
    setStatus("Выберите видео файл");
    return;
  }

  setStatus("Загружаю на YouTube... (не закрывай страницу)");
  setResult(null);

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
    setStatus("Ошибка upload: " + (parsed.data?.detail || parsed.raw));
    return;
  }

  const data = parsed.data;
  setStatus("Видео загружено ✅");
  setResult(data);
});

/* =========================
   INIT
========================= */

loadGallery().catch(() => {});

const btnRefreshGallery = document.getElementById("refresh_gallery_btn");
const previewGallery = document.getElementById("preview_gallery");

const API = window.location.origin;

async function loadGallery() {
  if (!previewGallery) return;

  const r = await fetch(`${API}/api/previews`, { method: "GET" });
  const text = await r.text();

  if (!r.ok) {
    throw new Error(text);
  }

  const data = JSON.parse(text);
  const items = data.items || [];

  previewGallery.innerHTML = "";

  if (items.length === 0) {
    previewGallery.innerHTML = `<div class="text-muted small">Пока нет превью в папке.</div>`;
    return;
  }

  for (const it of items) {
    const col = document.createElement("div");
    col.className = "col-6 col-md-4 col-lg-3";

    col.innerHTML = `
      <div class="card h-100 shadow-sm" style="cursor:pointer;">
        <img src="${it.url}?t=${Date.now()}" class="card-img-top" style="height:120px; object-fit:cover;">
        <div class="card-body p-2">
          <div class="small text-truncate" title="${it.name}">${it.name}</div>
          <button type="button" class="btn btn-sm btn-primary w-100 mt-1">Выбрать</button>
        </div>
      </div>
    `;

    col.querySelector("button").onclick = () => {
      previewFilenameEl.value = it.name;
      previewImg.src = it.url + "?t=" + Date.now();
      setStatus("Выбрано превью ✅");
    };

    previewGallery.appendChild(col);
  }
}

btnRefreshGallery?.addEventListener("click", async () => {
  try {
    setStatus("Обновляю галерею...");
    await loadGallery();
    setStatus("Галерея обновлена ✅");
  } catch (e) {
    setStatus("Ошибка");
    alert("Ошибка галереи: " + e.message);
  }
});

window.addEventListener("DOMContentLoaded", () => {
  loadGallery().catch(() => {});
});
