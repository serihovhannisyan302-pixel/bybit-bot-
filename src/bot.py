import os
import asyncio
import logging
from fastapi import FastAPI
import uvicorn
import ccxt.async_support as ccxt
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bybit_paper_trader")

app = FastAPI()

TELEGRAM_TOKEN = "9107764551:AAGWWaxreGFTeuRS0BJsz50BqN3LvhsOWXw"
CHAT_ID = "6264127581"

VIRTUAL_BALANCE = 100.0  
LEVERAGE = 15          # Плечо 15x
TAKE_PROFIT_PCT = 50.0 # Тейк-профит 50% к марже (3.33% цены)
STOP_LOSS_PCT = 20.0   # Стоп-лосс 20% к марже (1.33% цены)
CANDLE_LIMIT = 250      
TOP_COINS_COUNT = 50    
MIN_WIN_RATE = 38.0     

active_positions = []
sent_signals = set()
is_system_ready = False

async def send_telegram_alert(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Telegram error: {await response.text()}")
        except Exception as e:
            logger.error(f"Telegram request error: {e}")

@app.get("/")
async def root():
    return {
        "status": "running",
        "mode": "Optimized Pullback Paper Trader (Strategy 50:20 / 15x)",
        "virtual_balance": VIRTUAL_BALANCE,
        "active_positions_count": len(active_positions)
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
    if len(ohlcv) < 50:
        return 0.0
    recent_candles = ohlcv[-200:]
    success_count = 0
    total_simulations = 0

    for start_idx in range(5, len(recent_candles) - 10):
        if total_simulations >= 300:
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
        else:
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

async def monitor_and_trade_loop():
    global VIRTUAL_BALANCE, active_positions, sent_signals, is_system_ready
    exchange = ccxt.bybit({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

    try:
        while True:
            logger.info("🔄 Сканирование рынка (Стратегия 50:20)...")
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
                logger.error(f"Market data error: {e}")
                await asyncio.sleep(60)
                continue

            # 1. Проверка активных виртуальных позиций
            for pos in list(active_positions):
                try:
                    ticker = await exchange.fetch_ticker(pos['symbol'])
                    curr_price = ticker['last']
                    
                    if pos['direction'] == 'LONG':
                        if curr_price >= pos['tp']:
                            profit = pos['margin'] * (TAKE_PROFIT_PCT / 100)
                            VIRTUAL_BALANCE += profit
                            active_positions.remove(pos)
                            sent_signals.discard(pos['symbol'])
                            await send_telegram_alert(f"🟢 *ВИРТУАЛЬНЫЙ ТЕЙК-ПРОФИТ (+50%)*\nМонета: `{pos['symbol']}`\n🎯 Выход по цели: `{pos['tp']:.4f}`\n💰 Прибыль: `+${profit:.2f}`\n💼 Баланс банка: **${VIRTUAL_BALANCE:.2f}**")
                        elif curr_price <= pos['sl']:
                            loss = pos['margin'] * (STOP_LOSS_PCT / 100)
                            VIRTUAL_BALANCE -= loss
                            active_positions.remove(pos)
                            sent_signals.discard(pos['symbol'])
                            await send_telegram_alert(f"🔴 *ВИРТУАЛЬНЫЙ СТОП-ЛОСС (-20%)*\nМонета: `{pos['symbol']}`\n🛡 Сработал стоп: `{pos['sl']:.4f}`\n💸 Убыток: `-${loss:.2f}`\n💼 Баланс банка: **${VIRTUAL_BALANCE:.2f}**")
                    else:
                        if curr_price <= pos['tp']:
                            profit = pos['margin'] * (TAKE_PROFIT_PCT / 100)
                            VIRTUAL_BALANCE += profit
                            active_positions.remove(pos)
                            sent_signals.discard(pos['symbol'])
                            await send_telegram_alert(f"🟢 *ВИРТУАЛЬНЫЙ ТЕЙК-ПРОФИТ (+50%)*\nМонета: `{pos['symbol']}`\n🎯 Выход по цели: `{pos['tp']:.4f}`\n💰 Прибыль: `+${profit:.2f}`\n💼 Баланс банка: **${VIRTUAL_BALANCE:.2f}**")
                        elif curr_price >= pos['sl']:
                            loss = pos['margin'] * (STOP_LOSS_PCT / 100)
                            VIRTUAL_BALANCE -= loss
                            active_positions.remove(pos)
                            sent_signals.discard(pos['symbol'])
                            await send_telegram_alert(f"🔴 *ВИРТУАЛЬНЫЙ СТОП-ЛОСС (-20%)*\nМонета: `{pos['symbol']}`\n🛡 Сработал стоп: `{pos['sl']:.4f}`\n💸 Убыток: `-${loss:.2f}`\n💼 Баланс банка: **${VIRTUAL_BALANCE:.2f}**")
                except Exception as ex:
                    logger.error(f"Error checking position {pos['symbol']}: {ex}")

            # 2. Поиск новых точек входа
            cycle_candidates = []
            for symbol in symbols:
                if any(p['symbol'] == symbol for p in active_positions) or symbol in sent_signals:
                    continue 
                try:
                    ohlcv_5m = await exchange.fetch_ohlcv(symbol, timeframe='5m', limit=CANDLE_LIMIT)
                    ohlcv_1h = await exchange.fetch_ohlcv(symbol, timeframe='1h', limit=200)
                    ohlcv_4h = await exchange.fetch_ohlcv(symbol, timeframe='4h', limit=200)

                    if len(ohlcv_5m) < 200 or len(ohlcv_1h) < 200 or len(ohlcv_4h) < 200:
                        continue
                    
                    closes_5m = [c[4] for c in ohlcv_5m]
                    closes_1h = [c[4] for c in ohlcv_1h]
                    closes_4h = [c[4] for c in ohlcv_4h]
                    
                    ema_5m = calculate_ema(closes_5m, 200)
                    ema_1h = calculate_ema(closes_1h, 200)
                    ema_4h = calculate_ema(closes_4h, 200)

                    if not ema_5m or not ema_1h or not ema_4h:
                        continue
                    
                    current_price = closes_5m[-1]
                    
                    ema_distance_pct = abs((current_price - ema_5m) / ema_5m) * 100
                    if ema_distance_pct < 0.4 or ema_distance_pct > 2.2:
                        continue 

                    is_bullish = (current_price > ema_5m) and (closes_1h[-1] > ema_1h) and (closes_4h[-1] > ema_4h)
                    is_bearish = (current_price < ema_5m) and (closes_1h[-1] < ema_1h) and (closes_4h[-1] < ema_4h)

                    if not is_bullish and not is_bearish:
                        continue 

                    direction = 'LONG' if is_bullish else 'SHORT'
                    if not is_system_ready:
                        continue

                    win_rate = simulate_trade_probability(ohlcv_5m, direction)
                    if win_rate >= MIN_WIN_RATE:
                        cycle_candidates.append({
                            'symbol': symbol,
                            'direction': direction,
                            'current_price': current_price,
                            'win_rate': win_rate,
                            'distance': ema_distance_pct
                        })
                except Exception as ex:
                    logger.error(f"Error analyzing {symbol}: {ex}")

            if not is_system_ready:
                is_system_ready = True
                logger.info("🛡 Бот активирован: стратегия 50:20!")
                await asyncio.sleep(120)
                continue

            cycle_candidates.sort(key=lambda x: x['win_rate'], reverse=True)

            # Открытие всех подходящих сделок без ограничений
            for best in cycle_candidates:
                margin = VIRTUAL_BALANCE * 0.10  
                
                if best['direction'] == 'LONG':
                    tp = best['current_price'] * (1 + (TAKE_PROFIT_PCT / 100) / LEVERAGE)
                    sl = best['current_price'] * (1 - (STOP_LOSS_PCT / 100) / LEVERAGE)
                else:
                    tp = best['current_price'] * (1 - (TAKE_PROFIT_PCT / 100) / LEVERAGE)
                    sl = best['current_price'] * (1 + (STOP_LOSS_PCT / 100) / LEVERAGE)

                position = {
                    'symbol': best['symbol'],
                    'direction': best['direction'],
                    'entry_price': best['current_price'],
                    'margin': margin,
                    'tp': tp,
                    'sl': sl,
                    'win_rate': best['win_rate']
                }
                active_positions.append(position)
                sent_signals.add(best['symbol'])

                msg = (
                    f"🎯 *ВИРТУАЛЬНАЯ СДЕЛКА ОТКРЫТА*\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 Монета: `{best['symbol']}` | Направление: **{best['direction']}**\n"
                    f"📈 Win-Rate: `{best['win_rate']:.1f}%` | Отрыв EMA: `{best['distance']:.2f}%`\n"
                    f"💰 Маржа: `${margin:.2f}` (Плечо {LEVERAGE}x)\n"
                    f"📍 **Цена входа:** `{best['current_price']:.4f}`\n"
                    f"🟢 **Тейк-профит:** `{tp:.4f}` (+50% / +3.33% цены)\n"
                    f"🔴 **Стоп-лосс:** `{sl:.4f}` (-20% / -1.33% цены)\n"
                    f"💼 Баланс: **${VIRTUAL_BALANCE:.2f}**"
                )
                await send_telegram_alert(msg)

            logger.info(f"💤 Цикл завершен. Активных всего: {len(active_positions)}. Баланс: ${VIRTUAL_BALANCE:.2f}")
            await asyncio.sleep(120)

    except Exception as e:
        logger.error(f"Critical error: {e}")
    finally:
        await exchange.close()

@app.on_event("startup")
async def startup_event():
    await send_telegram_alert("🚀 *Бот обновлен: установлена оптимальная стратегия 50:20 (Плечо 15x, R:R 2.5:1)!*")
    asyncio.create_task(monitor_and_trade_loop())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("bot:app", host="0.0.0.0", port=port)
