import requests
import json
import os
import xml.etree.ElementTree as ET

# Токен и канал берутся из переменных окружения (секретов GitHub),
# в коде их не храним — это безопаснее.
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
STATE_FILE = "message_id.json"


def get_rates():
    # Курс USD/KZT — официальный сайт Нацбанка РК, без ключа
    r = requests.get("https://nationalbank.kz/rss/rates_all.xml", timeout=15)
    root = ET.fromstring(r.content)

    usd_kzt = None
    for item in root.findall(".//item"):
        code = item.find("title").text
        if code == "USD":
            usd_kzt = float(item.find("description").text.replace(",", "."))
            break

    if usd_kzt is None:
        raise RuntimeError("Не удалось найти курс USD в ответе Нацбанка РК")

    # Курс BTC/KZT — CoinGecko, без ключа
    btc = requests.get(
        "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=kzt",
        timeout=15,
    ).json()
    btc_kzt = btc["bitcoin"]["kzt"]

    return usd_kzt, btc_kzt


def build_text(usd_kzt, btc_kzt):
    return (
        "💱 Курс валют\n\n"
        f"USD: {usd_kzt:,.2f} ₸\n"
        f"BTC: {btc_kzt:,.0f} ₸\n\n"
        "Обновляется автоматически"
    )


def send_or_edit():
    usd_kzt, btc_kzt = get_rates()
    text = build_text(usd_kzt, btc_kzt)

    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            message_id = json.load(f)["message_id"]

        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText",
            data={"chat_id": CHAT_ID, "message_id": message_id, "text": text},
        )
        result = r.json()
        if not result.get("ok"):
            # Если сообщение не найдено (удалено вручную и т.п.) — создаём новое
            print("Не удалось отредактировать, создаю новое сообщение:", result)
            create_new(text)
        else:
            print("Сообщение обновлено")
    else:
        create_new(text)


def create_new(text):
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text},
    )
    result = r.json()
    if not result.get("ok"):
        raise RuntimeError(f"Ошибка отправки сообщения: {result}")

    message_id = result["result"]["message_id"]

    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/pinChatMessage",
        data={"chat_id": CHAT_ID, "message_id": message_id},
    )

    with open(STATE_FILE, "w") as f:
        json.dump({"message_id": message_id}, f)

    print("Создано и закреплено новое сообщение, id:", message_id)


if __name__ == "__main__":
    send_or_edit()
