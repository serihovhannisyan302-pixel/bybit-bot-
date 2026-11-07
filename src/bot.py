import os
import time
import requests
import ccxt

# 1. Загрузка параметров и ключей из переменных окружения
API_KEY = os.getenv('BYBIT_API_KEY')
API_SECRET = os.getenv('BYBIT_SECRET')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

TIMEFRAME = '15m'
LEVERAGE = 5
POSITION_SIZE_USD = 10  # Маржа $10 (объем с плечом $50)
STOP_LOSS_PCT = 0.018   # Стоп-лосс 1.8%
TP1_PCT = 0.03          # Тейк-профит 3%

# Инициализация подключения к Bybit (Futures / Unified)
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
        # Фильтруем активные линейные USDT-фьючерсы
        symbols = [
            market['symbol'] for market in exchange.markets.values()
            if market['linear'] and market['active'] and market['quote'] == 'USDT'
        ]
        
        # Получаем тикеры для сортировки по суточному объему торгов
        tickers = exchange.fetch_tickers(symbols)
        
        # Сортируем монеты по объему торгов (quoteVolume) в убывающем порядке
        sorted_symbols = sorted(
            [s for s in symbols if s in tickers and tickers[s]['quoteVolume']],
            key=lambda x: tickers[x]['quoteVolume'],
            reverse=True
        )
        
        # Возвращаем топ N монеты
        return sorted_symbols[:limit]
    except Exception as e:
        print(f"Ошибка получения списка монеты: {e}")
        # Резервный список на случай сбоя API
        return ['ZEC/USDT:USDT', 'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT']

def check_volume_breakout(symbol):
    """Проверка всплеска объема 4x-5x на 15m timeframe для конкретной монеты"""
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
        # Снижаем уровень логирования для редких ошибок сети по отдельным монетам
        pass
    return False, 0

def monitor_active_position(symbol, entry_price, side):
    """Отслеживание открытой позиции"""
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
    send_telegram("🤖 <b>Мультисканер (Топ-50 монет) запущен и сканирует рынок 24/7!</b>")

    while True:
        try:
            print("Обновление списка топ-50 монет...")
            top_symbols = get_top_symbols(50)
            print(f"Сканируем {len(top_symbols)} монет...")

            for symbol in top_symbols:
                breakout, ratio = check_volume_breakout(symbol)
                if breakout:
                    print(f"Найден импульс на {symbol}! Радио: {ratio:.2f}x")
                    
                    # Установка кредитного плеча для монеты
                    try:
                        exchange.set_leverage(LEVERAGE, symbol)
                    except:
                        pass

                    ticker = exchange.fetch_ticker(symbol)
                    price = ticker['last']
                    
                    amount = (POSITION_SIZE_USD * LEVERAGE) / price
                    
                    # Открытие LONG ордера
                    order = exchange.create_market_buy_order(symbol, amount)
                    entry_price = float(order.get('price', price))
                    
                    # Стоп-лосс
                    sl_price = entry_price * (1 - STOP_LOSS_PCT)
                    exchange.create_order(
                        symbol=symbol,
                        type='stop_market',
                        side='sell',
                        amount=amount,
                        params={'stopPrice': sl_price, 'reduceOnly': True}
                    )
                    
                    # Переходим в мониторинг сделки
                    monitor_active_position(symbol, entry_price, 'BUY')
                    
                # Небольшая пауза между запросами монет, чтобы не превысить лимиты биржи
                time.sleep(1)

        except Exception as e:
            print(f"Ошибка в общем цикле сканирования: {e}")
            
        # Пауза перед следующим полным кругом сканирования топ-50
        time.sleep(30)

if __name__ == '__main__':
    main()
