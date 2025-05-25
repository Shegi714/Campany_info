import requests
import json
import time
import os
from math import ceil
from collections import defaultdict
from datetime import datetime

# === CONFIGURATION ===
WB_HEADERS = {
    'accept': 'application/json',
    'Authorization': os.environ['WB_TOKEN']  # <-- GitHub Secret
}

TELEGRAM_BOT_TOKEN = os.environ['TG_TOKEN']  # <-- GitHub Secret
TELEGRAM_CHAT_ID = os.environ['TG_CHAT_ID']  # <-- GitHub Secret

TODAY = datetime.now().strftime('%Y-%m-%d')


def send_telegram_message(message: str):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    }

    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
        print("✅ Сообщение отправлено в Telegram.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка отправки в Telegram: {e}")


def get_orders():
    url = f'https://statistics-api.wildberries.ru/api/v1/supplier/orders?dateFrom={TODAY}'
    res = requests.get(url, headers=WB_HEADERS)
    res.raise_for_status()
    orders = res.json()

    srid_map = defaultdict(list)
    for order in orders:
        order_date = order.get("date", "")[:10]
        srid = order.get("srid")

        if srid and order_date == TODAY:
            srid_map[srid].append(order)

    final_orders = []
    for srid, entries in srid_map.items():
        latest = max(entries, key=lambda o: datetime.fromisoformat(o["lastChangeDate"]))
        price = latest.get("priceWithDisc", 0)
        if price > 0:
            final_orders.append(price)

    return len(final_orders), int(sum(final_orders))


def get_advert_ids():
    url = 'https://advert-api.wildberries.ru/adv/v1/promotion/count'
    res = requests.get(url, headers=WB_HEADERS)
    res.raise_for_status()
    data = res.json()

    advert_ids = []
    for group in data.get("adverts", []):
        if group.get("status") in [9, 11]:
            for ad in group.get("advert_list", []):
                advert_ids.append({
                    "id": ad["advertId"],
                    "dates": [TODAY]
                })

    return advert_ids


def chunk_list(lst, chunk_size=100):
    for i in range(0, len(lst), chunk_size):
        yield lst[i:i + chunk_size]


def get_advert_stats(advert_payload, order_sum):
    if not advert_payload:
        return (0, 0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0)

    url = 'https://advert-api.wildberries.ru/adv/v2/fullstats'
    headers = {
        'accept': 'application/json',
        'Authorization': WB_HEADERS['Authorization'],
        'Content-Type': 'application/json'
    }

    total_views = total_clicks = total_orders = 0
    total_cost = total_sum_price = 0.0
    chunks = list(chunk_list(advert_payload, 100))

    for idx, chunk in enumerate(chunks, 1):
        while True:
            try:
                body = json.dumps(chunk, ensure_ascii=False)
                print(f"📤 Отправка чанка {idx}/{len(chunks)} ({len(chunk)} кампаний)")
                res = requests.post(url, headers=headers, data=body)

                if res.status_code == 429:
                    print("⚠️ 429 Too Many Requests — ждём 60 секунд...")
                    time.sleep(60)
                    continue

                res.raise_for_status()
                stats = res.json()
                break

            except requests.exceptions.HTTPError as e:
                if res.status_code == 429:
                    print("⚠️ Повторный 429 — ждём 60 секунд...")
                    time.sleep(60)
                else:
                    print(f"❌ Ошибка: {e}")
                    raise

        for entry in stats:
            for day in entry.get("days", []):
                total_views += day.get("views", 0)
                total_clicks += day.get("clicks", 0)
                total_orders += day.get("orders", 0)
                total_cost += day.get("sum", 0.0)
                total_sum_price += day.get("sum_price", 0.0)

        if idx < len(chunks):
            print("⏳ Ждём 60 секунд...")
            time.sleep(60)

    # ✅ Правильное место для return
    ctr = (total_clicks / total_views * 100) if total_views else 0
    cpm = (total_cost / total_views * 1000) if total_views else 0
    cpc = (total_cost / total_clicks) if total_clicks else 0
    cpo = (total_cost / total_orders) if total_orders else 0
    drr = (total_cost / order_sum * 100) if order_sum else 0

    return (total_views, total_clicks, total_orders, int(total_sum_price),
            total_cost, ctr, cpm, cpc, cpo, drr)



def debug_run():
    try:
        print(f"📅 Дата запроса: {TODAY}")
        order_count, order_sum = get_orders()
        advert_payload = get_advert_ids()

        (
            views, clicks, adv_orders, adv_sum_price,
            adv_cost, ctr, cpm, cpc, cpo, drr
        ) = get_advert_stats(advert_payload, order_sum)

        message = (
            f"Заказы   {order_count}шт., {order_sum:,}руб. \n"
            f"Затраты {round(adv_cost):,}\n"
            f"ДРР       {round(drr, 2)}%\n"
            f"________________\n"
            f"Показы   {views:,}\n"
            f"Клики        {clicks:,}\n"
            f"Заказы Рек  {adv_orders} шт\n"
            f"                        {adv_sum_price:,} руб \n"
            f"CTR ~ {round(ctr, 2)}%\n"
            f"CPM ~ {round(cpm, 1)}\n"
            f"CPC ~ {round(cpc, 1)}\n"
            f"CPO ~ {round(cpo, 1)}"
        )

        print("\n🧾 Сообщение:\n")
        print(message)

        send_telegram_message(message)

    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    debug_run()
