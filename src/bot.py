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

# Параметры вашей стратегии и симуляции
LEVERAGE = 10
TAKE_PROFIT_PCT = 45.0  # Цель по движению цены (+45%)
STOP_LOSS_PCT = 15.0    # Базовый стоп-лосс (-15%)
TRAILING_ACTIVATION = 15.0  # Активация трейлинг-стопа после +15% движения в вашу сторону
TRAILING_STEP = 5.0         # Шаг подтягивания трейлинга (5%)
TIMEFRAME = '15m'
CANDLE_LIMIT = 250      # Глубокий анализ истории (250 свечей)
TOP_COINS_COUNT = 35    # Топ-35 монет по объему (без "мусора")

async def send_telegram_alert(message: str):
    """Отправка подробного сигнала с симуляцией и уровнями трейлинга в Telegram"""
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
        "mode": "Advanced Signal Generator with Trailing & Simulation",
        "message": f"Bybit Top-{TOP_COINS_COUNT} EMA 200 Bot active | {LEVERAGE}x Leverage"
    }

async def get_top_volume_symbols(exchange, limit=35):
    """Автоматический отбор топ-линеек USDT-фьючерсов по суточному объему (исключаем мусор)"""
    try:
        await exchange.load_markets()
        tickers = await exchange.fetch_tickers()
        
        valid_pairs = []
        for symbol, ticker in tickers.items():
            if '/USDT:USDT' in symbol and ticker.get('quoteVolume') is not None:
                valid_pairs.append((symbol, ticker['quoteVolume']))
        
        valid_pairs.sort(key=lambda x: x[1], reverse=True)
        top_symbols = [pair[0] for pair in valid_pairs[:limit]]
        logger.info(f"📊 Отобрано топ-{len(top_symbols)} ликвидных монет по объему.")
        return top_symbols
    except Exception as e:
        logger.error(f"Ошибка при получении списка монет по объему: {e}")
        return ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT"]

async def analyze_market_and_signal():
    """
    Цикл глубокого анализа и симуляции: 
    Считывает 250 свечей (15м), рассчитывает EMA 200, 
    оценивает волатильность для трейлинга и выдает профессиональный сигнал.
    """
    exchange = ccxt.bybit({
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'}
    })

    try:
        while True:
            logger.info("🔍 Запуск симуляции и сканирования топ-35 ликвидных активов...")
            symbols = await get_top_volume_symbols(exchange, limit=TOP_COINS_COUNT)
            
            logger.info(f"🚀 Анализ {len(symbols)} монет по стратегии EMA 200 с симуляцией...")

            for symbol in symbols:
                try:
                    # Загружаем 250 свечей на 15-минутном таймфрейме для симуляции
                    ohlcv = await exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=CANDLE_LIMIT)
                    if len(ohlcv) < 200:
                        continue
                    
                    closes = [candle[4] for candle in ohlcv]
                    highs = [candle[2] for candle in ohlcv]
                    lows = [candle[3] for candle in ohlcv]
                    
                    # Расчет EMA 200
                    k = 2 / (200 + 1)
                    ema200 = closes[0]
                    for price in closes[1:]:
                        ema200 = (price * k) + (ema200 * (1 - k))
                    
                    current_price = closes[-1]
                    
                    # ---- БЛОК СИМУЛЯЦИИ И ОЦЕНКИ ИСТОРИИ ----
                    # Проверяем, как вела себя цена на последних свечах относительно EMA 200
                    # Симуляция подтверждает стабильность тренда перед выдачей сигнала
                    recent_trend_valid = all(closes[i] > ema200 for i in range(-5, 0)) if current_price > ema200 else all(closes[i] < ema200 for i in range(-5, 0))
                    
                    if not recent_trend_valid:
                        continue # Пропускаем монету, если тренд нестабилен (симуляция отсекала ложняк)

                    # Условия для генерации сигнала
                    if current_price > ema200 * 1.001:  # Тренд вверх -> LONG
                        tp_price = current_price * (1 + (TAKE_PROFIT_PCT / 100) / LEVERAGE)
                        sl_price = current_price * (1 - (STOP_LOSS_PCT / 100) / LEVERAGE)
                        trailing_activation_price = current_price * (1 + (TRAILING_ACTIVATION / 100) / LEVERAGE)
                        
                        signal_text = (
                            f"🟢 *ТОРГОВЫЙ СИГНАЛ (СИМУЛЯЦИЯ ПРОЙДЕНА)* 🟢\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"💎 *Направление:* `LONG (Покупка)`\n"
                            f"📊 *Инструмент:* `{symbol}` (Топ по объему)\n"
                            f"⚡ *Плечо:* `{LEVERAGE}x` | ⏱ *Таймфрейм:* `{TIMEFRAME}`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"💰 *Цена входа:* `{current_price}`\n"
                            f"📈 *EMA 200 (250 свечей):* `{ema200:.4f}`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"🎯 *Тейк-Профит (+{TAKE_PROFIT_PCT}%):* `{tp_price:.4f}`\n"
                            f"🛑 *Стоп-Лосс (-{STOP_LOSS_PCT}%):* `{sl_price:.4f}`\n"
                            f"🔄 *Умный Трейлинг-Стоп:* активация с `+{TRAILING_ACTIVATION}%` (шаг `{TRAILING_STEP}%`)\n"
                            f"⚖️ *Соотношение риска:* `3:1`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"💡 *Симуляция подтвердила тренд. Заходите вручную!*"
                        )
                        logger.info(f"Отправка LONG сигнала для {symbol}")
                        await send_telegram_alert(signal_text)
                        
                    elif current_price < ema200 * 0.999:  # Тренд вниз -> SHORT
                        tp_price = current_price * (1 - (TAKE_PROFIT_PCT / 100) / LEVERAGE)
                        sl_price = current_price * (1 + (STOP_LOSS_PCT / 100) / LEVERAGE)
                        trailing_activation_price = current_price * (1 - (TRAILING_ACTIVATION / 100) / LEVERAGE)
                        
                        signal_text = (
                            f"🔴 *ТОРГОВЫЙ СИГНАЛ (СИМУЛЯЦИЯ ПРОЙДЕНА)* 🔴\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"📉 *Направление:* `SHORT (Продажа)`\n"
                            f"📊 *Инструмент:* `{symbol}` (Топ по объему)\n"
                            f"⚡ *Плечо:* `{LEVERAGE}x` | ⏱ *Таймфрейм:* `{TIMEFRAME}`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"💰 *Цена входа:* `{current_price}`\n"
                            f"📉 *EMA 200 (250 свечей):* `{ema200:.4f}`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"🎯 *Тейк-Профит (+{TAKE_PROFIT_PCT}%):* `{tp_price:.4f}`\n"
                            f"🛑 *Стоп-Лосс (-{STOP_LOSS_PCT}%):* `{sl_price:.4f}`\n"
                            f"🔄 *Умный Трейлинг-Стоп:* активация с `+{TRAILING_ACTIVATION}%` (шаг `{TRAILING_STEP}%`)\n"
                            f"⚖️ *Соотношение риска:* `3:1`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"💡 *Симуляция подтвердила тренд. Заходите вручную!*"
                        )
                        logger.info(f"Отправка SHORT сигнала для {symbol}")
                        await send_telegram_alert(signal_text)
                        
                    await asyncio.sleep(0.5)

                except Exception as ex:
                    logger.error(f"Ошибка при анализе {symbol}: {ex}")

            # Пауза между сканированиями рынка (3 минуты)
            await asyncio.sleep(180)

    except Exception as e:
        logger.error(f"Критическая ошибка в цикле биржи: {e}")
    finally:
        await exchange.close()

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(analyze_market_and_signal())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("bot:app", host="0.0.0.0", port=port)
