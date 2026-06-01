(function () {
  const textarea = document.getElementById("broadcast_message_html");
  const toolbar = document.querySelector("[data-editor-toolbar]");
  const preview = document.getElementById("broadcast_preview");
  const targetInput = document.getElementById("broadcast_target_usernames");
  const targetSummary = document.getElementById("broadcast_target_summary");
  const targetCards = Array.from(document.querySelectorAll("[data-broadcast-target]"));

  if (!textarea || !toolbar) {
    return;
  }

  const previewFallback =
    "<b>Предпросмотр сообщения</b><br><br>Начни печатать текст слева, и здесь появится пример того, как это будет выглядеть после отправки.";

  function replaceSelection(before, after, fallbackText = "") {
    const start = textarea.selectionStart ?? 0;
    const end = textarea.selectionEnd ?? 0;
    const value = textarea.value;
    const selected = value.slice(start, end);

    if (selected.startsWith(before) && selected.endsWith(after) && selected.length >= (before.length + after.length)) {
      const unwrapped = selected.slice(before.length, selected.length - after.length);
      textarea.setRangeText(unwrapped, start, end, "select");
      textarea.focus();
      textarea.setSelectionRange(start, start + unwrapped.length);
      return;
    }

    const outerStart = start - before.length;
    const outerEnd = end + after.length;
    if (
      outerStart >= 0 &&
      outerEnd <= value.length &&
      value.slice(outerStart, start) === before &&
      value.slice(end, outerEnd) === after
    ) {
      const inner = value.slice(start, end);
      textarea.setRangeText(inner, outerStart, outerEnd, "select");
      textarea.focus();
      textarea.setSelectionRange(outerStart, outerStart + inner.length);
      return;
    }

    const inner = selected || fallbackText;
    const replacement = `${before}${inner}${after}`;
    textarea.setRangeText(replacement, start, end, "end");
    const cursorStart = start + before.length;
    const cursorEnd = cursorStart + inner.length;
    textarea.focus();
    textarea.setSelectionRange(cursorStart, cursorEnd);
  }

  function insertLink() {
    const url = window.prompt("Вставь ссылку для Telegram:", "https://");
    if (!url) {
      return;
    }
    const start = textarea.selectionStart ?? 0;
    const end = textarea.selectionEnd ?? 0;
    const selected = textarea.value.slice(start, end) || "текст ссылки";
    const replacement = `<a href="${url}">${selected}</a>`;
    textarea.setRangeText(replacement, start, end, "end");
    textarea.focus();
    updatePreview();
  }

  function updatePreview() {
    if (!preview) {
      return;
    }
    const value = textarea.value.trim();
    preview.innerHTML = value || previewFallback;
  }

  function updateTargetUi() {
    const selected = new Set(
      String(targetInput?.value || "")
        .split(",")
        .map((item) => item.trim().toLowerCase())
        .filter(Boolean)
    );
    targetCards.forEach((card) => {
      const username = (card.dataset.broadcastTarget || "").trim().toLowerCase();
      const mark = card.querySelector(".broadcast-target-card__mark");
      const isSelected = selected.has(username);
      card.classList.toggle("is-selected", Boolean(isSelected));
      if (mark) {
        mark.textContent = isSelected ? "ВЫБРАН" : "НЕ ВЫБРАН";
      }
    });

    if (targetSummary) {
      targetSummary.textContent = selected.size > 0
        ? `Сейчас выбрано: ${selected.size} получ.`
        : "Сейчас выбрано: все получатели";
    }
  }

  toolbar.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) {
      return;
    }

    const action = button.dataset.action || "";
    const wrap = button.dataset.wrap || "";

    if (action === "link") {
      insertLink();
      return;
    }

    if (!wrap.includes("|")) {
      return;
    }

    const [before, after] = wrap.split("|");
    replaceSelection(before, after, "");
    updatePreview();
  });

  targetCards.forEach((card) => {
    card.addEventListener("click", () => {
      if (!targetInput) {
        return;
      }
      const username = (card.dataset.broadcastTarget || "").trim();
      const selected = new Set(
        String(targetInput.value || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean)
      );
      if (selected.has(username)) {
        selected.delete(username);
      } else {
        selected.add(username);
      }
      targetInput.value = Array.from(selected).join(",");
      updateTargetUi();
    });
  });

  textarea.addEventListener("input", updatePreview);
  updatePreview();
  updateTargetUi();
})();
