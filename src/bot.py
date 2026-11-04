import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.parse
import json

# ==================== НАСТРОЙКИ СТРАТЕГИИ ====================
TELEGRAM_BOT_TOKEN = "9107764551:AAGWWaxreGFTeuRS0BJsz50BqN3LvhsOWXw"
TELEGRAM_CHAT_ID = "6264127581"

LEVERAGE = 10         
RISK_REWARD_RATIO = 3 
EMA_PERIOD = 200      
INTERVAL = "15"       # Таймфрейм 15 минут
TOP_LIMIT = 35        
# ============================================================

# 1. Легковесный HTTP-сервер для Render (защита от засыпания)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# Запускаем веб-сервер в фоне
server_thread = threading.Thread(target=run_web_server, daemon=True)
server_thread.start()

def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as response:
            pass
    except Exception as e:
        print(f"Telegram error: {e}")

def get_top_trending_symbols(limit=35):
    try:
        url = "https://api.bybit.com/v5/market/tickers?category=linear"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode("utf-8"))
            if res["retCode"] == 0:
                tickers = res["result"]["list"]
                usdt_tickers = [
                    t for t in tickers 
                    if t["symbol"].endswith("USDT") and not t["symbol"].startswith("USDC")
                ]
                usdt_tickers.sort(key=lambda x: float(x.get("turnover24h", 0)), reverse=True)
                return [t["symbol"] for t in usdt_tickers[:limit]]
    except Exception as e:
        print(f"Bybit API error: {e}")
    return []

def get_klines(symbol, interval, limit=250):
    try:
        url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval={interval}&limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode("utf-8"))
            if res["retCode"] == 0:
                list_data = res["result"]["list"]
                list_data.reverse()
                return [float(candle[4]) for candle in list_data]
    except:
        pass
    return None

def calculate_ema(data, period):
    if len(data) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(data[:period]) / period
    for price in data[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def main():
    print("Бот успешно запущен на 15m таймфрейме и начал сканирование рынка...")
    
    start_msg = (
        f"💎 **EMA 200 TRADING SYSTEM** 🚀\n"
        f"═══════════════════════\n"
        f"⚡ **Статус:** `Активен (Live)`\n"
        f"⏱ **Таймфрейм:** `15m`\n"
        f"🎯 **Цель:** TP `+45%` | SL `-15%`\n"
        f"🔥 **Сканер:** Топ-{TOP_LIMIT} монет по объему\n"
        f"═══════════════════════"
    )
    send_telegram_message(start_msg)

    last_signal_time = {}
    COOLDOWN_TIME = 3600  # 1 час паузы по монете

    while True:
        try:
            symbols = get_top_trending_symbols(TOP_LIMIT)
            if not symbols:
                print("Не удалось получить список монет, повтор через 30 секунд...")
                time.sleep(30)
                continue

            current_time = time.time()

            for symbol in symbols:
                closes = get_klines(symbol, INTERVAL, limit=250)
                if not closes or len(closes) < EMA_PERIOD:
                    continue

                ema_200 = calculate_ema(closes, EMA_PERIOD)
                current_price = closes[-1]
                prev_price = closes[-2]

                last_sent = last_signal_time.get(symbol, 0)
                if current_time - last_sent < COOLDOWN_TIME:
                    time.sleep(0.5)
                    continue

                # Расчет уровней для LONG
                if prev_price <= ema_200 and current_price > ema_200:
                    tp_price = current_price * 1.045
                    sl_price = current_price * 0.985
                    
                    msg = (
                        f"🟢 **NEW LONG SIGNAL // BYBIT** 📈\n"
                        f"═══════════════════════\n"
                        f"🔹 **Монета:** `{symbol}`\n"
                        f"📍 **Точка входа:** `{current_price}`\n"
                        f"📊 **Индикатор EMA 200:** `{round(ema_200, 4)}`\n"
                        f"═══════════════════════\n"
                        f"🎯 **TAKE PROFIT (+45%):** `✨ {round(tp_price, 4)}`\n"
                        f"🛑 **STOP LOSS (-15%):** `🛡 {round(sl_price, 4)}`\n"
                        f"═══════════════════════\n"
                        f"⚡ **Плечо:** `{LEVERAGE}x` | 🎯 **R/R:** `{RISK_REWARD_RATIO}:1`\n"
                        f"⏰ **Таймфрейм:** `15m`"
                    )
                    send_telegram_message(msg)
                    last_signal_time[symbol] = current_time
                    print(f"Отправлен LONG сигнал по монете: {symbol}")

                # Расчет уровней для SHORT
                elif prev_price >= ema_200 and current_price < ema_200:
                    tp_price = current_price * 0.955
                    sl_price = current_price * 1.015
                    
                    msg = (
                        f"🔴 **NEW SHORT SIGNAL // BYBIT** 📉\n"
                        f"═══════════════════════\n"
                        f"🔹 **Монета:** `{symbol}`\n"
                        f"📍 **Точка входа:** `{current_price}`\n"
                        f"📊 **Индикатор EMA 200:** `{round(ema_200, 4)}`\n"
                        f"═══════════════════════\n"
                        f"🎯 **TAKE PROFIT (+45%):** `✨ {round(tp_price, 4)}`\n"
                        f"🛑 **STOP LOSS (-15%):** `🛡 {round(sl_price, 4)}`\n"
                        f"═══════════════════════\n"
                        f"⚡ **Плечо:** `{LEVERAGE}x` | 🎯 **R/R:** `{RISK_REWARD_RATIO}:1`\n"
                        f"⏰ **Таймфрейм:** `15m`"
                    )
                    send_telegram_message(msg)
                    last_signal_time[symbol] = current_time
                    print(f"Отправлен SHORT сигнал по монете: {symbol}")

                time.sleep(1)

            time.sleep(120)

        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
