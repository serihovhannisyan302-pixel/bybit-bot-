import asyncio
import threading
import ccxt.pro as ccxt
import pandas as pd
import numpy as np
import aiohttp
from fastapi import FastAPI

# --- НАСТРОЙКИ BYBIT (ЗАМЕНИ НА СВОИ КЛЮЧИ) ---
exchange = ccxt.bybit({
    'apiKey': 'ВАШ_BYBIT_API_KEY',
    'secret': 'ВАШ_BYBIT_SECRET_KEY',
    'options': {'defaultType': 'linear'}
})

TIMEFRAME = '15m'
LEVERAGE = 10
RISK_PERCENT = 0.10

# --- НАСТРОЙКИ TELEGRAM (ТВОИ ДАННЫЕ) ---
TELEGRAM_TOKEN = '9107764551:AAGWWaxreGFTeuRS0BJsz50BqN3LvhsOWXw'
TELEGRAM_CHAT_ID = '6264127581'

SYMBOLS_POOL = [
    'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'XRP/USDT:USDT', 
    'ADA/USDT:USDT', 'DOGE/USDT:USDT', 'AVAX/USDT:USDT', 'LINK/USDT:USDT', 
    'DOT/USDT:USDT', 'MATIC/USDT:USDT', 'NEAR/USDT:USDT', 'UNI/USDT:USDT', 
    'ATOM/USDT:USDT', 'ICP/USDT:USDT', 'LTC/USDT:USDT', 'APT/USDT:USDT', 
    'FTM/USDT:USDT', 'RNDR/USDT:USDT', 'INJ/USDT:USDT', 'TIA/USDT:USDT', 
    'ARB/USDT:USDT', 'OP/USDT:USDT', 'SUI/USDT:USDT', 'SEI/USDT:USDT', 
    'PEPE/USDT:USDT', 'SHIB/USDT:USDT', 'RENDER/USDT:USDT', 'JUP/USDT:USDT', 
    'DYDX/USDT:USDT', 'GALA/USDT:USDT', 'CRV/USDT:USDT', 'KAS/USDT:USDT', 
    'FIL/USDT:USDT', 'ETC/USDT:USDT', 'BCH/USDT:USDT'
]

app = FastAPI()

@app.get("/")
def health_check():
    """Эндпоинт для поддержания активности бота на Render"""
    return {"status": "Bot is running live!"}

async def send_telegram_message(text: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': text, 'parse_mode': 'Markdown'}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as response:
                pass
    except Exception as e:
        print(f"Ошибка Telegram: {e}")

def calculate_indicators(ohlcv) -> pd.DataFrame:
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    df['ATR'] = np.max(ranges, axis=1).rolling(14).mean()
    
    plus_dm = df['high'].diff().clip(lower=0)
    minus_dm = df['low'].diff().clip(lower=0)
    tr14 = df['ATR'].rolling(14).sum()
    plus_di = 100 * (plus_dm.rolling(14).sum() / tr14)
    minus_di = 100 * (minus_dm.rolling(14).sum() / tr14)
    df['ADX'] = (100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)).rolling(14).mean()
    
    return df

async def analyze_symbol(symbol: str):
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=250)
        df = calculate_indicators(ohlcv)
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        close = last['close']
        ema = last['EMA_200']
        atr = last['ATR']
        avg_atr = df['ATR'].rolling(20).mean().iloc[-1]
        adx = last['ADX']
        
        if atr < (avg_atr * 0.7) or adx < 23:
            return
            
        body_size = abs(close - last['open'])
        avg_body = abs(df['close'] - df['open']).rolling(20).mean().iloc[-1]
        
        signal = None
        if prev['close'] <= prev['EMA_200'] and close > ema and body_size >= (avg_body * 1.2):
            signal = 'BUY'
        elif prev['close'] >= prev['EMA_200'] and close < ema and body_size >= (avg_body * 1.2):
            signal = 'SELL'
            
        if signal:
            await execute_trade_async(symbol, signal, close)
    except Exception:
        pass

async def execute_trade_async(symbol: str, signal: str, entry_price: float):
    try:
        balance_info = await exchange.fetch_balance()
        balance = balance_info['USDT']['free']
        margin_to_risk = balance * RISK_PERCENT
        
        if signal == 'BUY':
            stop_loss = entry_price * (1 - 0.015)
            take_profit = entry_price * (1 + 0.045)
            emoji = '🟢 **LONG (ПОКУПКА)**'
        else:
            stop_loss = entry_price * (1 + 0.015)
            take_profit = entry_price * (1 - 0.045)
            emoji = '🔴 **SHORT (ПРОДАЖА)**'
            
        msg = (
            f"{emoji}\n"
            f"📌 Монета: `{symbol}`\n"
            f"💰 Цена входа: `{entry_price}`\n"
            f"🛑 Стоп-лосс (-1.5%): `{stop_loss:.2f}`\n"
            f"🎯 Тейк-профит (+4.5%): `{take_profit:.2f}`\n"
            f"⚖️ Риск (10%): `${margin_to_risk:.2f} (Плечо {LEVERAGE}x)`"
        )
        
        await send_telegram_message(msg)
        
        # Автоматическая торговля на Bybit (раскомментируй для реальной работы)
        # await exchange.set_leverage(LEVERAGE, symbol)
        # await exchange.create_order(symbol, 'market', signal.lower(), (margin_to_risk * LEVERAGE) / entry_price)
    except Exception as e:
        await send_telegram_message(f"❌ Ошибка ордера по {symbol}: {e}")

async def background_trading_loop():
    """Фоновый цикл сканирования рынка"""
    await asyncio.sleep(5)  генерация паузы при старте сервера
    await send_telegram_message("🚀 Бот успешно запущен на Render! Пул из 35 монет под защитой.")
    
    try:
        await exchange.load_markets()
        while True:
            tasks = [analyze_symbol(symbol) for symbol in SYMBOLS_POOL]
            await asyncio.gather(*tasks)
            await asyncio.sleep(60)
    except Exception as e:
        print(f"Критическая ошибка цикла: {e}")
    finally:
        await exchange.close()

def run_bg_loop():
    asyncio.run(background_trading_loop())

@app.on_event("startup")
def startup_event():
    """Запуск торгового потока параллельно с веб-сервером FastAPI"""
    t = threading.Thread(target=run_bg_loop, daemon=True)
    t.start()
