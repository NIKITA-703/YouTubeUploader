from google import genai

# The client gets the API key from the environment variable `GEMINI_API_KEY`.
client = genai.Client(api_key="")

response = client.models.generate_content(
    model="gemini-2.5-flash", contents="Напиши только ТЕГИ И НИЧЕГО БОЛЬШЕ. Надо сделать теги под название видео [BEAT SWITCH] Travis Scott x Future x UTOPIA Type Beat - Safety [EPIC INTRO and OUTRO] Пример тегов #TravisScottTypeBeat #MikeDeanTypeBeat #futuretypebeat "
)
print(response.text)

