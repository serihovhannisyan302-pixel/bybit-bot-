import os
import asyncio
import logging
from fastapi import FastAPI
import uvicorn
import ccxt.async_support as ccxt
import aiohttp

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bybit_bot")

app = FastAPI()

# Ваши данные Telegram
TELEGRAM_TOKEN = "9107764551:AAGWWaxreGFTeuRS0BJsz50BqN3LvhsOWXw"
CHAT_ID = "6264127581"

# Параметры стратегии
LEVERAGE = 10
TAKE_PROFIT_PCT = 45.0  
STOP_LOSS_PCT = 15.0    
CANDLE_LIMIT = 250      
TOP_COINS_COUNT = 35    
MAX_SIGNALS_PER_CYCLE = 1  # Строго 1 лучший сигнал за проход!

# Реестр для защиты от спама
sent_signals = set()

async def send_telegram_alert(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Не удалось отправить сообщение в Telegram: {await response.text()}")
        except Exception as e:
            logger.error(f"Ошибка запроса к Telegram API: {e}")

@app.get("/")
async def root():
    return {
        "status": "running", 
        "mode": "Multi-Timeframe EMA 200 Bot with Single Best Signal Filter (Production)",
        "message": f"Bybit Top-{TOP_COINS_COUNT} Bot active"
    }

def calculate_ema(closes, period=200):
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = (price * k) + (ema * (1 - k))
    return ema

def simulate_trade_probability(ohlcv, direction: str) -> float:
    """
    Симуляция сделок на истории. Возвращает точный Win-Rate (процент успеха).
    """
    if len(ohlcv) < 50:
        return 0.0
    
    recent_candles = ohlcv[-200:]
    success_count = 0
    total_simulations = 0

    for start_idx in range(5, len(recent_candles) - 10):
        if total_simulations >= 500:
            break
            
        entry = recent_candles[start_idx][4]
        if direction == 'LONG':
            tp = entry * (1 + (TAKE_PROFIT_PCT / 100) / LEVERAGE)
            sl = entry * (1 - (STOP_LOSS_PCT / 100) / LEVERAGE)
            
            hit_tp, hit_sl = False, False
            for j in range(start_idx + 1, len(recent_candles)):
                high, low = recent_candles[j][2], recent_candles[j][3]
                if low <= sl:
                    hit_sl = True
                    break
                if high >= tp:
                    hit_tp = True
                    break
            if hit_tp and not hit_sl:
                success_count += 1
            total_simulations += 1
        else: # SHORT
            tp = entry * (1 - (TAKE_PROFIT_PCT / 100) / LEVERAGE)
            sl = entry * (1 + (STOP_LOSS_PCT / 100) / LEVERAGE)
            
            hit_tp, hit_sl = False, False
            for j in range(start_idx + 1, len(recent_candles)):
                high, low = recent_candles[j][2], recent_candles[j][3]
                if high >= sl:
                    hit_sl = True
                    break
                if low <= tp:
                    hit_tp = True
                    break
            if hit_tp and not hit_sl:
                success_count += 1
            total_simulations += 1

    if total_simulations == 0:
        return 0.0

    return (success_count / total_simulations) * 100

async def analyze_market_and_signal():
    global sent_signals
    exchange = ccxt.bybit({
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'},
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    })

    try:
        while True:
            logger.info("🔄 Сканирование рынка в поисках абсолютного лидера...")
            try:
                await exchange.load_markets()
                tickers = await exchange.fetch_tickers()
                
                valid_pairs = []
                for symbol, ticker in tickers.items():
                    if '/USDT:USDT' in symbol and ticker.get('quoteVolume') is not None:
                        valid_pairs.append((symbol, ticker['quoteVolume']))
                
                valid_pairs.sort(key=lambda x: x[1], reverse=True)
                symbols = [pair[0] for pair in valid_pairs[:TOP_COINS_COUNT]]
            except Exception as e:
                logger.error(f"Ошибка загрузки рынков: {e}")
                await asyncio.sleep(60)
                continue

            cycle_candidates = []

            for symbol in symbols:
                try:
                    ohlcv_15m = await exchange.fetch_ohlcv(symbol, timeframe='15m', limit=CANDLE_LIMIT)
                    ohlcv_1h = await exchange.fetch_ohlcv(symbol, timeframe='1h', limit=220)
                    ohlcv_4h = await exchange.fetch_ohlcv(symbol, timeframe='4h', limit=220)

                    if len(ohlcv_15m) < 200 or len(ohlcv_1h) < 200 or len(ohlcv_4h) < 200:
                        continue
                    
                    closes_15m = [c[4] for c in ohlcv_15m]
                    closes_1h = [c[4] for c in ohlcv_1h]
                    closes_4h = [c[4] for c in ohlcv_4h]
                    
                    ema_15m = calculate_ema(closes_15m, 200)
                    ema_1h = calculate_ema(closes_1h, 200)
                    ema_4h = calculate_ema(closes_4h, 200)

                    if not ema_15m or not ema_1h or not ema_4h:
                        continue
                    
                    current_price = closes_15m[-1]

                    is_bullish = (current_price > ema_15m) and (closes_1h[-1] > ema_1h) and (closes_4h[-1] > ema_4h)
                    is_bearish = (current_price < ema_15m) and (closes_1h[-1] < ema_1h) and (closes_4h[-1] < ema_4h)

                    if not is_bullish and not is_bearish:
                        if symbol in sent_signals:
                            sent_signals.discard(symbol)
                        continue 

                    direction = 'LONG' if is_bullish else 'SHORT'
                    
                    # Прогон симуляции 500 сделок
                    win_rate = simulate_trade_probability(ohlcv_15m, direction)
                    
                    # Порог качества (например, Win-Rate не ниже 42%)
                    if win_rate >= 42.0:
                        cycle_candidates.append({
                            'symbol': symbol,
                            'direction': direction,
                            'current_price': current_price,
                            'ema_15m': ema_15m,
                            'win_rate': win_rate
                        })

                except Exception as ex:
                    logger.error(f"Ошибка по монете {symbol}: {ex}")

            # Сортируем кандидатов по самому высокому Win-Rate (первым идет абсолютный лидер)
            cycle_candidates.sort(key=lambda x: x['win_rate'], reverse=True)

            sent_count = 0
            for candidate in cycle_candidates:
                symbol = candidate['symbol']
                direction = candidate['direction']
                current_price = candidate['current_price']
                ema_15m = candidate['ema_15m']
                win_rate = candidate['win_rate']

                if symbol not in sent_signals and sent_count < MAX_SIGNALS_PER_CYCLE:
                    if direction == 'LONG':
                        tp_price = current_price * (1 + (TAKE_PROFIT_PCT / 100) / LEVERAGE)
                        sl_price = current_price * (1 - (STOP_LOSS_PCT / 100) / LEVERAGE)
                        
                        signal_text = (
                            f"🟢 *ЛУЧШИЙ СИГНАЛ ЦИКЛА (Win-Rate: {win_rate:.1f}%)* 🟢\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"💎 *Направление:* `LONG (Покупка)`\n"
                            f"📊 *Инструмент:* `{symbol}`\n"
                            f"⚡ *Плечо:* `{LEVERAGE}x` | ⏱ *Таймфреймы:* `15m + 1h + 4h`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"💰 *Цена входа:* `{current_price}`\n"
                            f"📈 *EMA 200 (15m):* `{ema_15m:.4f}`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"🎯 *Тейк-Профит (+{TAKE_PROFIT_PCT}%):* `{tp_price:.4f}`\n"
                            f"🛑 *Стоп-Лосс (-{STOP_LOSS_PCT}%):* `{sl_price:.4f}`\n"
                            f"⚖️ *Соотношение риска:* `3:1`"
                        )
                        await send_telegram_alert(signal_text)
                        sent_signals.add(symbol)
                        sent_count += 1
                        
                    elif direction == 'SHORT':
                        tp_price = current_price * (1 - (TAKE_PROFIT_PCT / 100) / LEVERAGE)
                        sl_price = current_price * (1 + (STOP_LOSS_PCT / 100) / LEVERAGE)
                        
                        signal_text = (
                            f"🔴 *ЛУЧШИЙ СИГНАЛ ЦИКЛА (Win-Rate: {win_rate:.1f}%)* 🔴\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"📉 *Направление:* `SHORT (Продажа)`\n"
                            f"📊 *Инструмент:* `{symbol}`\n"
                            f"⚡ *Плечо:* `{LEVERAGE}x` | ⏱ *Таймфреймы:* `15m + 1h + 4h`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"💰 *Цена входа:* `{current_price}`\n"
                            f"📉 *EMA 200 (15m):* `{ema_15m:.4f}`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"🎯 *Тейк-Профит (-{TAKE_PROFIT_PCT}%):* `{tp_price:.4f}`\n"
                            f"🛑 *Стоп-Лосс (+{STOP_LOSS_PCT}%):* `{sl_price:.4f}`\n"
                            f"⚖️ *Соотношение риска:* `3:1`"
                        )
                        await send_telegram_alert(signal_text)
                        sent_signals.add(symbol)
                        sent_count += 1

            logger.info(f"💤 Цикл завершен. Отправлен 1 лучший сигнал (если были кандидаты). Пауза 3 минуты.")
            await asyncio.sleep(180)

    except Exception as e:
        logger.error(f"Критическая ошибка цикла: {e}")
    finally:
        await exchange.close()

@app.on_event("startup")
async def startup_event():
    await send_telegram_alert("🤖 *Бот настроен на отправку только 1 лучшего сигнала за цикл!*")
    asyncio.create_task(analyze_market_and_signal())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("bot:app", host="0.0.0.0", port=port)
