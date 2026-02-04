import sqlite3
import hashlib

from app.database import DB_PATH


def _hash_pass(username, password):
    return hashlib.sha256(f"{username}:{password}".encode()).hexdigest()


def seed_users():

    # username password email inst telegram beatstars(1/0)
    users = [
        ("kellmipenis", "sinep213#", "kellmibeats@gmail.com", "@kellmibeats", "@KellmiStoree", 1),
        ("spacech1ld", "feel@stro%", "NONE", "@spacech1ld.music", "@twentyfive_mp3", 0),
        ("sunly", "m@@norsun?", "NONE", "@sunlybeatz", "@sunlybeatz", 0),
        ("lvbuba", "viet@ncutebeer$$", "NONE", "@lvbuba", "@lvbuba_prod", 0),
        ("plak1!", "pl@kpl@kra!n", "NONE", "NONE", "@plak1beatz", 0),
        ("tr1pl_s", "$bigboy@budabi$", "NONE", "@tr1pl_s", "@tr1plsbeatz", 0),
    ]

    conn = sqlite3.connect(str(DB_PATH))
    for u, p, email, ig, tg, bs in users:
        h = _hash_pass(u, p)  # Хэшируем
        conn.execute('''
                INSERT OR REPLACE INTO users (username, password_hash, email, instagram, telegram, has_beatstars)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (u, h, email, ig, tg, bs))

    conn.commit()
    conn.close()
    print("=== Users added DB ===")


if __name__ == "__main__":
    seed_users()