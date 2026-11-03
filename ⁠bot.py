import os
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.parse
import json

# ==================== НАСТРОЙКИ СТРАТЕГИИ ====================
TELEGRAM_BOT_TOKEN = "9107764551:AAGWWaxreGFTeuRS0BJsz50BqN3LvhsOWXw"
TELEGRAM_CHAT_ID = "6264127581"

LEVERAGE = 10         # Торговое плечо
RISK_REWARD_RATIO = 3 # Соотношение 3:1
EMA_PERIOD = 200      # Период EMA
INTERVAL = "5"        # Таймфрейм в минутах (5 минут)
TOP_LIMIT = 35        # Количество топ-монет для анализа за раз
# ============================================================


# 1. Мини-сервер для Render (удерживает порт открытым 24/7)
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bybit Trend Scalping Bot is active!")
        
    def log_message(self, format, *args):
        pass

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()


# 2. Функция отправки сигналов в Telegram
def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as response:
            pass
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")


# 3. Получение топ-монет по суточному объему с Bybit (linear фьючерсы)
def get_top_trending_symbols(limit=35):
    try:
        url = "https://api.bybit.com/v5/market/tickers?category=linear"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode("utf-8"))
            if res["retCode"] == 0:
                tickers = res["result"]["list"]
                # Фильтруем только USDT пары, исключаем стейблкоины
                usdt_tickers = [
                    t for t in tickers 
                    if t["symbol"].endswith("USDT") and not t["symbol"].startswith("USDC")
                ]
                
                # Сортируем по торговому обороту за 24 часа (turnover24h) от большего к меньшему
                usdt_tickers.sort(key=lambda x: float(x.get("turnover24h", 0)), reverse=True)
                
                # Берем топ N монет
                top_symbols = [t["symbol"] for t in usdt_tickers[:limit]]
                return top_symbols
    except Exception as e:
        print(f"Ошибка получения списка топ-монет: {e}")
    return []


# 4. Получение исторических данных свечей
def get_klines(symbol, interval, limit=250):
    try:
        url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval={interval}&limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode("utf-8"))
            if res["retCode"] == 0:
                list_data = res["result"]["list"]
                list_data.reverse()
                closes = [float(candle[4]) for candle in list_data]
                return closes
    except Exception as e:
        pass
    return None


# 5. Расчет EMA
def calculate_ema(data, period):
    if len(data) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(data[:period]) / period
    for price in data[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


# 6. Основной цикл анализа
def main():
    start_msg = (
        "🚀 *Авто-сканер топ трендовых монет запущен!*\n"
        f"📊 Стратегия: Пересечение EMA {EMA_PERIOD} (5m)\n"
        f"🎯 Risk/Reward: {RISK_REWARD_RATIO}:1 | Плечо: {LEVERAGE}x\n"
        f"🔥 Анализирует топ-{TOP_LIMIT} монет по объему за 24ч."
    )
    print("Бот успешно запущен!")
    send_telegram_message(start_msg)

    while True:
        try:
            # Динамически получаем актуальный топ самых движущихся монет за день
            symbols = get_top_trending_symbols(TOP_LIMIT)
            if not symbols:
                time.sleep(30)
                continue

            print(f"Сканирование топ-{len(symbols)} активных монет...")

            for symbol in symbols:
                closes = get_klines(symbol, INTERVAL, limit=250)
                if not closes or len(closes) < EMA_PERIOD:
                    continue

                ema_200 = calculate_ema(closes, EMA_PERIOD)
                current_price = closes[-1]
                prev_price = closes[-2]

                # Логика пересечения EMA 200 (Лонг)
                if prev_price <= ema_200 and current_price > ema_200:
                    msg = (
                        f"🟢 *СИГНАЛ НА ПОКУПКУ (LONG)*\n"
                        f"🪙 Монета: `{symbol}`\n"
                        f"📈 Цена: `{current_price}`\n"
                        f"📉 EMA 200: `{round(ema_200, 4)}`\n"
                        f"⚡ Плечо: `{LEVERAGE}x`\n"
                        f"🎯 Take Profit (3:1)"
                    )
                    send_telegram_message(msg)

                # Логика пересечения EMA 200 (Шорт)
                elif prev_price >= ema_200 and current_price < ema_200:
                    msg = (
                        f"🔴 *СИГНАЛ НА ПРОДАЖУ (SHORT)*\n"
                        f"🪙 Монета: `{symbol}`\n"
                        f"📈 Цена: `{current_price}`\n"
                        f"📉 EMA 200: `{round(ema_200, 4)}`\n"
                        f"⚡ Плечо: `{LEVERAGE}x`\n"
                        f"🎯 Take Profit (3:1)"
                    )
                    send_telegram_message(msg)

                time.sleep(1) # Небольшая пауза между монетами

            # Пауза перед следующим полным кругом сканирования рынка
            time.sleep(120)

        except Exception as e:
            print(f"Ошибка в цикле: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
