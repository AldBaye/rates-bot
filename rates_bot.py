import requests
import json
import os
import xml.etree.ElementTree as ET

BOT_TOKEN = os.environ["BOT_TOKEN"]
CLIENTS_FILE = "clients.json"

# ---------------------------------------------------------------------------
# "Рецепты" валют. Чтобы добавить новую валюту из уже существующего
# источника — просто добавь сюда новую строку. Чтобы добавить новый
# источник — допиши функцию fetch_* ниже и укажи её здесь как "source".
# ---------------------------------------------------------------------------
CURRENCY_SPECS = {
    "USD_KZT": {"source": "nacbank", "code": "USD", "unit": "₸", "decimals": 2},
    "EUR_KZT": {"source": "nacbank", "code": "EUR", "unit": "₸", "decimals": 2},
    "RUB_KZT": {"source": "nacbank", "code": "RUB", "unit": "₸", "decimals": 2},
    "BTC_USD": {"source": "coingecko", "id": "bitcoin", "unit": "$", "decimals": 0},
    "ETH_USD": {"source": "coingecko", "id": "ethereum", "unit": "$", "decimals": 0},
    "USD_RUB": {"source": "cbr", "code": "USD", "unit": "₽", "decimals": 2},
    "EUR_RUB": {"source": "cbr", "code": "EUR", "unit": "₽", "decimals": 2},
}


def fetch_nacbank():
    """Курсы Нацбанка РК к тенге. Возвращает {код: курс за 1 единицу}."""
    r = requests.get("https://nationalbank.kz/rss/rates_all.xml", timeout=15)
    root = ET.fromstring(r.content)

    rates = {}
    for item in root.findall(".//item"):
        code = item.find("title").text
        value = float(item.find("description").text.replace(",", "."))
        quant_el = item.find("quant")
        quant = float(quant_el.text) if quant_el is not None else 1.0
        rates[code] = value / quant
    return rates


def fetch_coingecko(ids):
    """Курсы крипты в долларах. ids — множество id вида {'bitcoin','ethereum'}."""
    if not ids:
        return {}
    joined = ",".join(sorted(ids))
    r = requests.get(
        f"https://api.coingecko.com/api/v3/simple/price?ids={joined}&vs_currencies=usd",
        timeout=15,
    )
    data = r.json()
    return {coin_id: data[coin_id]["usd"] for coin_id in ids if coin_id in data}


def fetch_cbr():
    """Курсы ЦБ РФ к рублю. Возвращает {код: курс за 1 единицу}."""
    r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=15)
    data = r.json()
    rates = {}
    for code, info in data["Valute"].items():
        rates[code] = info["Value"] / info["Nominal"]
    return rates


def fetch_all_rates(needed_currency_codes):
    """
    Смотрит, какие источники реально нужны (по всем клиентам разом),
    и запрашивает каждый источник только один раз — а не по разу на клиента.
    """
    needed_sources = {CURRENCY_SPECS[c]["source"] for c in needed_currency_codes}
    raw = {}

    if "nacbank" in needed_sources:
        raw["nacbank"] = fetch_nacbank()

    if "coingecko" in needed_sources:
        ids = {
            CURRENCY_SPECS[c]["id"]
            for c in needed_currency_codes
            if CURRENCY_SPECS[c]["source"] == "coingecko"
        }
        raw["coingecko"] = fetch_coingecko(ids)

    if "cbr" in needed_sources:
        raw["cbr"] = fetch_cbr()

    values = {}
    for currency_code in needed_currency_codes:
        spec = CURRENCY_SPECS[currency_code]
        source = spec["source"]
        if source == "coingecko":
            values[currency_code] = raw["coingecko"][spec["id"]]
        else:
            values[currency_code] = raw[source][spec["code"]]

    return values


def build_text(client, values):
    lines = []
    for currency_code in client["currencies"]:
        spec = CURRENCY_SPECS[currency_code]
        label = currency_code.split("_")[0]
        value = values[currency_code]
        lines.append(f"{label}: {value:,.{spec['decimals']}f} {spec['unit']}")
    return "\n".join(lines)


def send_or_edit(client, text):
    chat_id = client["chat_id"]
    message_id = client.get("message_id")

    if message_id:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText",
            data={"chat_id": chat_id, "message_id": message_id, "text": text},
        )
        result = r.json()
        if result.get("ok"):
            print(f"[{client['name']}] обновлено")
            return message_id

        description = result.get("description", "").lower()
        if "message is not modified" in description:
            print(f"[{client['name']}] курс не изменился, правка не нужна")
            return message_id

        print(f"[{client['name']}] не удалось отредактировать ({result}), создаю новое")

    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": chat_id, "text": text},
    )
    result = r.json()
    if not result.get("ok"):
        raise RuntimeError(f"Не удалось отправить сообщение: {result}")

    new_message_id = result["result"]["message_id"]
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/pinChatMessage",
        data={"chat_id": chat_id, "message_id": new_message_id},
    )
    print(f"[{client['name']}] создано и закреплено новое сообщение, id: {new_message_id}")
    return new_message_id


def main():
    with open(CLIENTS_FILE, encoding="utf-8") as f:
        clients = json.load(f)

    active_clients = [c for c in clients if c.get("active", True)]

    needed_currency_codes = {
        code for client in active_clients for code in client["currencies"]
    }
    values = fetch_all_rates(needed_currency_codes)

    changed = False
    for client in active_clients:
        try:
            text = build_text(client, values)
            new_message_id = send_or_edit(client, text)
            if new_message_id != client.get("message_id"):
                client["message_id"] = new_message_id
                changed = True
        except Exception as e:
            print(f"[{client.get('name', '???')}] ОШИБКА: {e}")

    if changed:
        with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(clients, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
