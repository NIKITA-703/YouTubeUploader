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

const successSound = new Audio('/static/sounds/success.mp3');
successSound.volume = 0.5; // Уровень громкости (от 0 до 1)

const lightbox = document.getElementById("glitch-lightbox");
const lightboxImg = document.getElementById("lightbox_img");
const lightboxCaption = document.getElementById("lightbox_caption");

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

regenHashtagsBtn?.addEventListener("click", async () => {
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
  lightbox.style.display = "block";
  lightboxImg.src = src;
  lightboxCaption.innerHTML = caption || "PREVIEW_ENLARGED";
  // Отключаем прокрутку страницы при открытом фото
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
  try {
    // Очищаем прошлые результаты и сбрасываем цвет статуса
    hideResult();
    if (statusEl) statusEl.style.color = "";

    const title = (titleEl.value || "").trim();
    if (!title) throw new Error("Введите название");

    setStatus("Gemini + превью: работаю...");

    const fd = new FormData();
    fd.append("title", title);
    fd.append("purchase_link", (purchaseLinkEl.value || "").trim());
    fd.append("bpm", bpmEl.value);
    fd.append("key", keyEl.value);

    const res = await fetch("/api/fill", { method: "POST", body: fd });
    const parsed = await safeJson(res);

    if (!parsed.ok) {
      throw new Error(parsed.data?.detail || parsed.raw || "Ошибка /api/fill");
    }

    const data = parsed.data;

    // Заполняем поля
    hashtagsEl.value = data.hashtags || "";
    seoEl.value = data.seo_tags || "";

    // Обновляем фото
    let previewStatus = "";
    if (data.preview_url) {
      previewImg.src = data.preview_url + "?t=" + Date.now();
      previewFilenameEl.value = data.preview_filename || "";
      previewStatus = " + Превью найдено";
    }

    await loadGallery();

    // --- ЛОГИКА ВЫВОДА ПРЕДУПРЕЖДЕНИЯ В БЛОК РЕЗУЛЬТАТА ---
    if (data.warning) {
      // Показываем оранжевый блок-карточку
      resultBox.innerHTML = `
        <div class="glitch-ai-warning">
          <b>AI_STATUS // SEMI_OFFLINE</b>
          ${data.warning}
          <small>> Поля заполнены стандартными тегами. <br> Проверьте их вручную.</small>
        </div>
      `;
      resultBox.classList.remove("d-none");

      // Статус сверху делаем нейтральным
      setStatus("⚠️ Готово (есть замечания)" + previewStatus);
    } else {
      // Если всё идеально
      setStatus("Готово ✅" + previewStatus);
    }

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


uploadBtn?.addEventListener("click", () => {
  try {
    hideResult();

    const title = (titleEl.value || "").trim();
    if (!title) throw new Error("Введите название");

    if (!videoEl.files || videoEl.files.length === 0) {
      throw new Error("Выберите видео файл");
    }

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
    fd.append("bpm", bpmEl.value);
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

      // --- красивый вывод (как раньше) ---
      const publishText = data.publish_at
      ? `${escapeHtml(String(data.publish_at))} (UTC)`
      : "NO_DATE";

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
