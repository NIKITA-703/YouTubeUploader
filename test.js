
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