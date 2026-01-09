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

function setStatus(msg) {
  statusEl.textContent = msg || "";
}

function setResult(obj) {
  resultEl.textContent = obj ? JSON.stringify(obj, null, 2) : "";
}

function addHistory(url) {
  const a = document.createElement("a");
  a.href = url;
  a.textContent = url;
  a.target = "_blank";
  a.rel = "noreferrer";
  historyEl.prepend(a);
}

clearBtn.addEventListener("click", () => {
  hashtagsEl.value = "";
  seoEl.value = "";
  publishEl.value = "";
  previewImg.src = "";
  previewFilenameEl.value = "";
  previewFileEl.value = "";
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

  const r = await fetch("/api/fill", { method: "POST", body: fd });
  if (!r.ok) {
    setStatus("Ошибка fill: " + await r.text());
    return;
  }

  const data = await r.json();
  hashtagsEl.value = data.hashtags || "";
  seoEl.value = data.seo_tags || "";

  previewImg.src = (data.preview_url || "") + "?t=" + Date.now();
  previewFilenameEl.value = data.preview_filename || "";

  if (data.preview_url) addHistory(data.preview_url);

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

  const r = await fetch("/api/preview/refresh", { method: "POST", body: fd });
  if (!r.ok) {
    setStatus("Ошибка refresh: " + await r.text());
    return;
  }

  const data = await r.json();
  previewImg.src = (data.preview_url || "") + "?t=" + Date.now();
  previewFilenameEl.value = data.preview_filename || "";

  if (data.preview_url) addHistory(data.preview_url);
  setStatus("Новое превью ✅");
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

  const r = await fetch("/api/upload", { method: "POST", body: fd });
  if (!r.ok) {
    setStatus("Ошибка upload: " + await r.text());
    return;
  }

  const data = await r.json();
//  setStatus("Видео загружено ✅ videoId: " + (data.video_id || ""));
  setStatus("Видео загружено ✅" ));
  setResult(data);
});
