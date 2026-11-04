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
TRAILING_ACTIVATION = 15.0  
TRAILING_STEP = 5.0         
TIMEFRAME = '15m'
CANDLE_LIMIT = 250      
TOP_COINS_COUNT = 35    

async def send_telegram_alert(message: str):
    """Отправка сообщения в Telegram"""
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
        "mode": "EMA 200 Trend Bot (Production)",
        "message": f"Bybit Top-{TOP_COINS_COUNT} Bot active"
    }

async def analyze_market_and_signal():
    """
    Основной цикл сканирования рынка по EMA 200
    """
    # Инициализация биржи с обходом ограничений через публичные заголовки
    exchange = ccxt.bybit({
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'},
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    })

    try:
        while True:
            logger.info("🔍 Сканирование топ-линеек USDT-фьючерсов...")
            try:
                await exchange.load_markets()
                tickers = await exchange.fetch_tickers()
                
                valid_pairs = []
                for symbol, ticker in tickers.items():
                    if '/USDT:USDT' in symbol and ticker.get('quoteVolume') is not None:
                        valid_pairs.append((symbol, ticker['quoteVolume']))
                
                valid_pairs.sort(key=lambda x: x[1], reverse=True)
                symbols = [pair[0] for pair in valid_pairs[:TOP_COINS_COUNT]]
                logger.info(f"📊 Успешно отобрано топ-{len(symbols)} монет.")
            except Exception as e:
                logger.error(f"Ошибка загрузки рынков (возможно, блокировка сети): {e}")
                await asyncio.sleep(60)
                continue

            for symbol in symbols:
                try:
                    ohlcv = await exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=CANDLE_LIMIT)
                    if len(ohlcv) < 200:
                        continue
                    
                    closes = [candle[4] for candle in ohlcv]
                    
                    # Расчет EMA 200
                    k = 2 / (200 + 1)
                    ema200 = closes[0]
                    for price in closes[1:]:
                        ema200 = (price * k) + (ema200 * (1 - k))
                    
                    current_price = closes[-1]
                    
                    # Проверка тренда
                    recent_trend_valid = all(closes[i] > ema200 for i in range(-5, 0)) if current_price > ema200 else all(closes[i] < ema200 for i in range(-5, 0))
                    
                    if not recent_trend_valid:
                        continue 

                    if current_price > ema200 * 1.001:  # LONG
                        tp_price = current_price * (1 + (TAKE_PROFIT_PCT / 100) / LEVERAGE)
                        sl_price = current_price * (1 - (STOP_LOSS_PCT / 100) / LEVERAGE)
                        
                        signal_text = (
                            f"🟢 *ТОРГОВЫЙ СИГНАЛ EMA 200* 🟢\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"💎 *Направление:* `LONG (Покупка)`\n"
                            f"📊 *Инструмент:* `{symbol}`\n"
                            f"⚡ *Плечо:* `{LEVERAGE}x` | ⏱ *Таймфрейм:* `{TIMEFRAME}`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"💰 *Цена входа:* `{current_price}`\n"
                            f"📈 *EMA 200:* `{ema200:.4f}`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"🎯 *Тейк-Профит (+{TAKE_PROFIT_PCT}%):* `{tp_price:.4f}`\n"
                            f"🛑 *Стоп-Лосс (-{STOP_LOSS_PCT}%):* `{sl_price:.4f}`\n"
                            f"⚖️ *Соотношение риска:* `3:1`"
                        )
                        await send_telegram_alert(signal_text)
                        
                    elif current_price < ema200 * 0.999:  # SHORT
                        tp_price = current_price * (1 - (TAKE_PROFIT_PCT / 100) / LEVERAGE)
                        sl_price = current_price * (1 + (STOP_LOSS_PCT / 100) / LEVERAGE)
                        
                        signal_text = (
                            f"🔴 *ТОРГОВЫЙ СИГНАЛ EMA 200* 🔴\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"📉 *Направление:* `SHORT (Продажа)`\n"
                            f"📊 *Инструмент:* `{symbol}`\n"
                            f"⚡ *Плечо:* `{LEVERAGE}x` | ⏱ *Таймфрейм:* `{TIMEFRAME}`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"💰 *Цена входа:* `{current_price}`\n"
                            f"📉 *EMA 200:* `{ema200:.4f}`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"🎯 *Тейк-Профит (-{TAKE_PROFIT_PCT}%):* `{tp_price:.4f}`\n"
                            f"🛑 *Стоп-Лосс (+{STOP_LOSS_PCT}%):* `{sl_price:.4f}`\n"
                            f"⚖️ *Соотношение риска:* `3:1`"
                        )
                        await send_telegram_alert(signal_text)
                        
                    await asyncio.sleep(1)

                except Exception as ex:
                    logger.error(f"Ошибка по монете {symbol}: {ex}")

            # Пауза перед следующим циклом сканирования (3 минуты)
            await asyncio.sleep(180)

    except Exception as e:
        logger.error(f"Критическая ошибка цикла: {e}")
    finally:
        await exchange.close()

@app.on_event("startup")
async def startup_event():
    await send_telegram_alert("🤖 *Бот успешно перезапущен и начал сканирование рынка!*")
    asyncio.create_task(analyze_market_and_signal())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("bot:app", host="0.0.0.0", port=port)
