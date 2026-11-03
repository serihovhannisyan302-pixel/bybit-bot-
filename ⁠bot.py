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
INTERVAL = "5"        
TOP_LIMIT = 35        
# ============================================================

# 1. Легковесный HTTP-сервер для Render
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
    print("Бот запущен!")
    send_telegram_message("🚀 *EMA 200 Bot запущен на Render!* Сканируем топ трендовых монет.")

    while True:
        try:
            symbols = get_top_trending_symbols(TOP_LIMIT)
            if not symbols:
                time.sleep(30)
                continue

            for symbol in symbols:
                closes = get_klines(symbol, INTERVAL, limit=250)
                if not closes or len(closes) < EMA_PERIOD:
                    continue

                ema_200 = calculate_ema(closes, EMA_PERIOD)
                current_price = closes[-1]
                prev_price = closes[-2]

                if prev_price <= ema_200 and current_price > ema_200:
                    msg = f"🟢 *LONG* | `{symbol}`\nЦена: `{current_price}`\nEMA 200: `{round(ema_200, 4)}`\nПлечо: `{LEVERAGE}x` (3:1)"
                    send_telegram_message(msg)
                elif prev_price >= ema_200 and current_price < ema_200:
                    msg = f"🔴 *SHORT* | `{symbol}`\nЦена: `{current_price}`\nEMA 200: `{round(ema_200, 4)}`\nПлечо: `{LEVERAGE}x` (3:1)"
                    send_telegram_message(msg)

                time.sleep(1)

            time.sleep(120)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
