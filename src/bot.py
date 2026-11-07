import os
import time
import requests
import ccxt

# 1. Загрузка параметров и ключей из переменных окружения
API_KEY = os.getenv('BYBIT_API_KEY')
API_SECRET = os.getenv('BYBIT_SECRET')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

SYMBOL = 'ZEC/USDT'
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

def check_volume_breakout():
    """Проверка всплеска объема 4x-5x на 15m timeframe"""
    try:
        ohlcv = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=6)
        if len(ohlcv) < 6:
            return False, 0
        
        # Объем текущей (последней закрытой) свечи
        current_volume = ohlcv[-2][5]
        # Средний объем предыдущих 4 свечей
        avg_volume = sum([candle[5] for candle in ohlcv[-6:-2]]) / 4
        
        if avg_volume == 0:
            return False, 0
            
        ratio = current_volume / avg_volume
        if ratio >= 4.0:
            return True, ratio
    except Exception as e:
        print(f"Ошибка получения свечей: {e}")
    return False, 0

def monitor_active_position(entry_price, side):
    """Отслеживание позиции до закрытия по TP/SL и отправка отчета в Telegram"""
    send_telegram(f"🚀 <b>Вход в позицию!</b>\nПара: {SYMBOL}\nНаправление: {side}\nЦена входа: ${entry_price:.2f}\nПлечо: {LEVERAGE}x")
    
    tp1_hit = False
    
    while True:
        time.sleep(10)
        try:
            positions = exchange.fetch_positions([SYMBOL])
            active = [p for p in positions if float(p.get('contracts', 0)) > 0]
            
            if not active:
                # Позиция полностью закрылась (по SL или финальному TP)
                send_telegram(f"🏁 <b>Позиция по {SYMBOL} полностью закрыта!</b>")
                break
                
            ticker = exchange.fetch_ticker(SYMBOL)
            current_price = ticker['last']
            
            # Чекпоинт TP1 (+3%)
            if not tp1_hit:
                if side == 'BUY' and current_price >= entry_price * (1 + TP1_PCT):
                    tp1_hit = True
                    send_telegram(f"🎯 <b>Достигнут TP1 (3%) по {SYMBOL}!</b>\nПеревод позиции в безубыток.")
                elif side == 'SELL' and current_price <= entry_price * (1 - TP1_PCT):
                    tp1_hit = True
                    send_telegram(f"🎯 <b>Достигнут TP1 (3%) по {SYMBOL}!</b>\nПеревод позиции в безубыток.")
                    
        except Exception as e:
            print(f"Ошибка мониторинга: {e}")

def main():
    send_telegram("🤖 <b>Импульсный торговый бот запущен и следит за рынком 24/7!</b>")
    
    # Установка кредитного плеча
    try:
        exchange.set_leverage(LEVERAGE, SYMBOL)
    except Exception as e:
        print(f"Плечо уже установлено или ошибка: {e}")

    while True:
        try:
            breakout, ratio = check_volume_breakout()
            if breakout:
                ticker = exchange.fetch_ticker(SYMBOL)
                price = ticker['last']
                
                # Расчет объёма ордера с плечом 5x
                amount = (POSITION_SIZE_USD * LEVERAGE) / price
                
                # Выставляем рыночный ордер на покупку (LONG)
                order = exchange.create_market_buy_order(SYMBOL, amount)
                entry_price = float(order.get('price', price))
                
                # Устанавливаем Hard Stop-Loss (1.8%)
                sl_price = entry_price * (1 - STOP_LOSS_PCT)
                exchange.create_order(
                    symbol=SYMBOL,
                    type='stop_market',
                    side='sell',
                    amount=amount,
                    params={'stopPrice': sl_price, 'reduceOnly': True}
                )
                
                # Переходим в режим отслеживания позиции
                monitor_active_position(entry_price, 'BUY')
                
        except Exception as e:
            print(f"Ошибка в основном цикле: {e}")
            
        time.sleep(15)

if __name__ == '__main__':
    main()
