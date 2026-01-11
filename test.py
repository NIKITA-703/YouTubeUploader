from google import genai

# The client gets the API key from the environment variable `GEMINI_API_KEY`.
client = genai.Client(api_key="")

response = client.models.generate_content(
    model="gemini-2.5-flash", contents="Напиши только ТЕГИ И НИЧЕГО БОЛЬШЕ. Надо сделать теги под название видео [BEAT SWITCH] Travis Scott x Future x UTOPIA Type Beat - Safety [EPIC INTRO and OUTRO] Пример тегов #TravisScottTypeBeat #MikeDeanTypeBeat #futuretypebeat "
)
print(response.text)


/* app/web/static/style.css */

.gallery-scroll {
  max-height: 520px;
  overflow-y: auto;
  background: #fff;
  border: 1px solid rgba(0,0,0,.125);
  border-radius: .5rem;
  padding: .5rem;
}

.preview-card {
  cursor: pointer;
  transition: transform .08s ease-in-out, box-shadow .08s ease-in-out;
}

.preview-card:hover {
  transform: translateY(-1px);
  box-shadow: 0 0.25rem 0.75rem rgba(0,0,0,.08);
}

.preview-card.selected {
  outline: 2px solid rgba(13,110,253,.8);
  outline-offset: 2px;
}

.preview-img {
  width: 100%;
  height: 110px;
  object-fit: cover;
}

.sticky-right {
  position: sticky;
  top: 16px;
}

/* =========================
   Theme switch
========================= */
.switch {
  font-size: 17px;
  position: relative;
  display: inline-block;
  width: 3.5em;
  height: 2em;
}

.switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  --background: #28096b;
  position: absolute;
  cursor: pointer;
  inset: 0;
  background-color: var(--background);
  transition: .5s;
  border-radius: 30px;
}

.slider:before {
  position: absolute;
  content: "";
  height: 1.4em;
  width: 1.4em;
  border-radius: 50%;
  left: 10%;
  bottom: 15%;
  box-shadow: inset 8px -4px 0px 0px #fff000;
  background: var(--background);
  transition: .5s;
}

.switch input:checked + .slider {
  background-color: #522ba7;
}

.switch input:checked + .slider:before {
  transform: translateX(100%);
  box-shadow: inset 15px -4px 0px 15px #fff000;
}

/* ========== DARK THEME ========== */

:root {
  --bg: #f8f9fa;
  --card-bg: #ffffff;
  --text: #212529;
}

body[data-theme="dark"] {
  --bg: #121212;
  --card-bg: #1e1e1e;
  --text: #eaeaea;
}

body {
  background-color: var(--bg) !important;
  color: var(--text);
}

.card {
  background-color: var(--card-bg);
  color: var(--text);
}

.form-control,
textarea {
  background-color: var(--card-bg);
  color: var(--text);
  border-color: #444;
}

.form-control:focus {
  background-color: var(--card-bg);
  color: var(--text);
}

.navbar {
  transition: background-color .3s;
}

