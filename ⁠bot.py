import time
import json
import urllib.request
import ssl

TELEGRAM_TOKEN = "9107764551:AAGWWaxreGFTeuRS0BJsz50BqN3LvhsOWXw"
CHAT_ID = "6264127581"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT"]
TIMEFRAME = "15"
EMA_PERIOD = 200
MARGIN = 10.0
LEVERAGE = 10
TP_PCT = 0.45
SL_PCT = 0.15

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

last_signals = {symbol: None for symbol in SYMBOLS}

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}).encode('utf-8')
    req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            pass
    except Exception as e:
        print(f"Ошибка отправки Telegram: {e}")

def get_klines(symbol):
    url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval={TIMEFRAME}&limit=205"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get('retCode') == 0:
                raw = data['result']['list']
                closes = [float(c[4]) for c in reversed(raw)]
                return closes
    except Exception as e:
        print(f"Ошибка получения данных для {symbol}: {e}")
    return None

def calculate_ema(data, period=200):
    if len(data) < period:
        return None
    multiplier = 2 / (period + 1)
    sma = sum(data[:period]) / period
    ema = sma
    for price in data[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def main():
    print("🚀 Торговый сканер Bybit запущен 24/7...")
    send_telegram("🚀 *Сканер EMA 200 успешно запущен и готов к работе!*")

    while True:
        try:
            for symbol in SYMBOLS:
                closes = get_klines(symbol)
                if not closes or len(closes) < 201:
                    continue

                prev_price = closes[-3]
                curr_price = closes[-2]

                ema_prev = calculate_ema(closes[:-2], EMA_PERIOD)
                ema_curr = calculate_ema(closes[:-1], EMA_PERIOD)

                if not ema_prev or not ema_curr:
                    continue

                signal = None
                if prev_price <= ema_prev and curr_price > ema_curr:
                    signal = "LONG 🟢"
                elif prev_price >= ema_prev and curr_price < ema_curr:
                    signal = "SHORT 🔴"

                if signal and last_signals[symbol] != signal:
                    last_signals[symbol] = signal
                    
                    entry = curr_price
                    if "LONG" in signal:
                        tp = entry * (1 + (TP_PCT / LEVERAGE))
                        sl = entry * (1 - (SL_PCT / LEVERAGE))
                    else:
                        tp = entry * (1 - (TP_PCT / LEVERAGE))
                        sl = entry * (1 + (SL_PCT / LEVERAGE))

                    msg = (
                        f"🚨 *СИГНАЛ: {symbol} [{signal}]*\n\n"
                        f"• *Таймфрейм:* {TIMEFRAME}m (EMA 200)\n"
                        f"• *Цена входа:* `{entry:.4f}`\n"
                        f"• *Плечо:* {LEVERAGE}x\n"
                        f"• *Маржа:* ${MARGIN:.2f}\n"
                        f"• *Take-Profit (+45%):* `{tp:.4f}` (+$4.50)\n"
                        f"• *Stop-Loss (-15%):* `{sl:.4f}` (-$1.50)\n\n"
                        f"⚡ _Заходи на Bybit и открывай позицию!_"
                    )
                    print(f"[{symbol}] Сигнал найден: {signal}")
                    send_telegram(msg)

            time.sleep(30)

        except Exception as e:
            print(f"Системная ошибка: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
