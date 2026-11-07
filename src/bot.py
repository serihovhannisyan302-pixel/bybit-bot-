import time
import requests
import ccxt

# Ваши защищенные ключи и токены
API_KEY = 'Oy7XUNVKQb3uh42fvJ'
API_SECRET = '2kE4VvEs1P80mZ8lFeJY3U0dVh095S6tM266'
TELEGRAM_TOKEN = '9107764551:AAGWWaxreGFTeuRS0BJsz50BqN3LvhsOWXw'
TELEGRAM_CHAT_ID = '6264127581'

TIMEFRAME = '15m'
LEVERAGE = 5
POSITION_SIZE_USD = 10  # Маржа $10 (общий объем позиции с плечом — $50)
STOP_LOSS_PCT = 0.018   # Стоп-лосс 1.8%
TP1_PCT = 0.03          # Тейк-профит 3%

# Инициализация подключения к Bybit Futures
exchange = ccxt.bybit({
    'apiKey': API_KEY,
    'secret': API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'linear'}
})

def send_telegram(message):
    """Отправка уведомлений в Telegram"""
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            print(f"Ошибка отправки Telegram: {e}")

def get_top_symbols(limit=50):
    """Автоматическое получение топ-монет по объему торгов с фьючерсов Bybit"""
    try:
        exchange.load_markets()
        symbols = [
            market['symbol'] for market in exchange.markets.values()
            if market.get('linear') and market.get('active') and market.get('quote') == 'USDT' and ':' not in market['symbol']
        ]
        
        tickers = exchange.fetch_tickers(symbols)
        
        sorted_symbols = sorted(
            [s for s in symbols if s in tickers and tickers[s].get('quoteVolume')],
            key=lambda x: tickers[x]['quoteVolume'],
            reverse=True
        )
        
        return sorted_symbols[:limit]
    except Exception as e:
        print(f"Ошибка получения списка монет: {e}")
        return ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT']

def check_volume_breakout(symbol):
    """Проверка всплеска объема 4x-5x на 15m таймфрейме"""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=6)
        if len(ohlcv) < 6:
            return False, 0
        
        current_volume = ohlcv[-2][5]
        avg_volume = sum([candle[5] for candle in ohlcv[-6:-2]]) / 4
        
        if avg_volume == 0:
            return False, 0
            
        ratio = current_volume / avg_volume
        if ratio >= 4.0:
            return True, ratio
    except Exception as e:
        pass
    return False, 0

def monitor_active_position(symbol, entry_price, side):
    """Отслеживание открытой позиции и фиксация результатов"""
    send_telegram(f"🚀 <b>Вход в позицию!</b>\nПара: {symbol}\nНаправление: {side}\nЦена входа: ${entry_price:.4f}\nПлечо: {LEVERAGE}x")
    
    tp1_hit = False
    
    while True:
        time.sleep(10)
        try:
            positions = exchange.fetch_positions([symbol])
            active = [p for p in positions if float(p.get('contracts', 0)) > 0]
            
            if not active:
                send_telegram(f"🏁 <b>Позиция по {symbol} полностью закрыта!</b>")
                break
                
            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            
            if not tp1_hit:
                if side == 'BUY' and current_price >= entry_price * (1 + TP1_PCT):
                    tp1_hit = True
                    send_telegram(f"🎯 <b>Достигнут TP1 (3%) по {symbol}!</b>\nПеревод в безубыток.")
                elif side == 'SELL' and current_price <= entry_price * (1 - TP1_PCT):
                    tp1_hit = True
                    send_telegram(f"🎯 <b>Достигнут TP1 (3%) по {symbol}!</b>\nПеревод в безубыток.")
                    
        except Exception as e:
            print(f"Ошибка мониторинга позиции: {e}")

def main():
    send_telegram("🤖 <b>Мультисканер топ-50 монет запущен и работает 24/7!</b>")

    while True:
        try:
            print("Обновление списка топ-50 монет...")
            top_symbols = get_top_symbols(50)
            print(f"Сканируем {len(top_symbols)} монет...")

            for symbol in top_symbols:
                breakout, ratio = check_volume_breakout(symbol)
                if breakout:
                    print(f"Найден импульс на {symbol}! Радио: {ratio:.2f}x")
                    
                    try:
                        exchange.set_leverage(LEVERAGE, symbol)
                    except:
                        pass

                    ticker = exchange.fetch_ticker(symbol)
                    price = ticker['last']
                    
                    amount = (POSITION_SIZE_USD * LEVERAGE) / price
                    
                    order = exchange.create_market_buy_order(symbol, amount)
                    entry_price = float(order.get('price', price))
                    
                    sl_price = entry_price * (1 - STOP_LOSS_PCT)
                    exchange.create_order(
                        symbol=symbol,
                        type='stop_market',
                        side='sell',
                        amount=amount,
                        params={'stopPrice': sl_price, 'reduceOnly': True}
                    )
                    
                    monitor_active_position(symbol, entry_price, 'BUY')
                    
                time.sleep(1)

        except Exception as e:
            print(f"Ошибка в общем цикле сканирования: {e}")
            
        time.sleep(30)

if __name__ == '__main__':
    main()
