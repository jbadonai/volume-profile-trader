import asyncio
import aiohttp
import logging
import time
import sys
from datetime import datetime, time as dtime

# --- Use Windows Selector Event Loop Policy on Windows to avoid proactor issues ---
if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# --- Telegram Settings ---
TELEGRAM_BOT_TOKEN = "7670784421:AAEL2j8knz5Klg1kzRx-HAJpCllbzEux28Q"
TELEGRAM_CHAT_ID = "6590880408"

# --- Default Scanner Settings ---
DEFAULT_INTERVAL = "5m"
SYMBOLS = [
    'DOTUSDT', 'ADAUSDT', '1INCHUSDT', 'XRPUSDT', 'ARUSDT', 'MAVUSDT', 'MANAUSDT', 'INJUSDT',
    'ONTUSDT', 'JTOUSDT', 'COMPUSDT', 'EGLDUSDT', 'HIFIUSDT', 'MASKUSDT', 'BATUSDT', 'XAIUSDT',
    'HOOKUSDT', 'SUPERUSDT', 'UNIUSDT', 'STEEMUSDT', 'NKNUSDT', 'MAGICUSDT', 'GASUSDT', 'SXPUSDT',
    'FETUSDT', 'DENTUSDT', 'ONEUSDT', 'ALICEUSDT', 'LSKUSDT', 'OXTUSDT', 'NFPUSDT', 'DYDXUSDT',
    'RDNTUSDT', 'GMTUSDT', 'MINAUSDT', 'TRBUSDT', 'SUSHIUSDT', 'YGGUSDT', 'ACEUSDT', 'CHZUSDT',
    'AVAXUSDT', 'GRTUSDT', 'MTLUSDT', 'LPTUSDT', 'TRUUSDT', 'TLMUSDT', 'CELRUSDT', 'KSMUSDT',
    'DYMUSDT', 'SFPUSDT', 'BLURUSDT', 'QNTUSDT', 'CTSIUSDT', 'ETHUSDT', 'HOTUSDT', 'TRXUSDT',
    'ICPUSDT', 'XTZUSDT', 'ALGOUSDT', 'VETUSDT', 'SPELLUSDT', 'ZRXUSDT', 'CHRUSDT', 'BALUSDT',
    'ICXUSDT', 'ETCUSDT', 'FILUSDT', 'JASMYUSDT', 'FXSUSDT', 'CYBERUSDT', 'ALPHAUSDT', 'ILVUSDT',
     'STXUSDT', 'CELOUSDT', 'AIUSDT', 'IDUSDT', 'SANDUSDT', 'ROSEUSDT', 'BTCUSDT',
    'DOGEUSDT', 'SOLUSDT', 'STGUSDT', 'THETAUSDT', 'RIFUSDT', 'OPUSDT', 'CAKEUSDT', 'JOEUSDT',
    'LQTYUSDT', 'TIAUSDT', 'KAITOUSDT', 'GALAUSDT', 'RONINUSDT', 'ACHUSDT', 'FUNUSDT',
    'ONGUSDT', 'SEIUSDT', 'SKLUSDT', 'TUSDT', 'RVNUSDT'
]
CONCURRENT_LIMIT = 10  # Limit concurrent requests
SCAN_INTERVAL = 60  # Seconds between scans

# Global dictionary to track last trade advice per symbol
last_trade_advice = {}

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BINANCE_API_URL = "https://api.binance.com/api/v3/klines"
EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"


async def fetch_binance_data(session, symbol):
    """Fetch historical data from Binance asynchronously."""
    url = f"{BINANCE_API_URL}?symbol={symbol}&interval={DEFAULT_INTERVAL}&limit=100"
    try:
        async with session.get(url) as response:
            data = await response.json()
            if isinstance(data, list):
                logging.info(f"[{symbol}] Fetched historical data with {len(data)} rows.")
                return symbol, data
            else:
                logging.error(f"[{symbol}] API Error: {data}")
    except Exception as e:
        logging.error(f"[{symbol}] Fetch Error: {e}")
    return symbol, None


async def get_tick_size(session, symbol):
    """Retrieve tick size for the symbol using Binance exchange info."""
    try:
        async with session.get(EXCHANGE_INFO_URL) as response:
            info = await response.json()
            for s in info.get("symbols", []):
                if s.get("symbol") == symbol:
                    for f in s.get("filters", []):
                        if f.get("filterType") == "PRICE_FILTER":
                            tick = float(f.get("tickSize", 0.0001))
                            logging.info(f"[{symbol}] Tick size: {tick}")
                            return tick
    except Exception as e:
        logging.error(f"[{symbol}] Tick size error: {e}")
    return 0.0001


async def calculate_trade_advice(symbol, data, tick):
    """
    Process fetched data and determine trade advice.
    For this example, we simulate:
      - Entry: last candle's close price.
      - For BUY trades: TP = VAH, where VAH = Entry * 1.0020.
      - For SELL trades: TP = VAL, where VAL = Entry * 0.9980.
      - SL is calculated using a risk-reward of 1:2.
    """
    if not data:
        logging.error(f"[{symbol}] No historical data available.")
        return symbol, "WAIT", None

    try:
        entry = float(data[-1][4])  # Last candle's close price
    except Exception as e:
        logging.error(f"[{symbol}] Error parsing entry price: {e}")
        return symbol, "WAIT", None

    # Simulated targets (replace with real volume profile calculations as needed)
    vah = entry * 1.0020  # For BUY target
    val = entry * 0.9980  # For SELL target

    # Determine advice based on entry relative to targets
    if entry >= vah:
        advice = "SELL"
    elif entry <= val:
        advice = "BUY"
    else:
        advice = "WAIT"

    # Calculate SL using risk-reward 1:2
    if advice == "BUY":
        TP = vah
        risk = (TP - entry) / 2  # Half the distance (in price) becomes risk
        SL = entry - risk
    elif advice == "SELL":
        TP = val
        risk = (entry - TP) / 2
        SL = entry + risk
    else:
        TP = SL = entry

    details = {
        "Entry": round(entry, 4),
        "SL": round(SL, 4),
        "TP": round(TP, 4),
        "POC": round((vah + val) / 2, 4),  # Simulated POC as mid of VAH and VAL
        "VAH": round(vah, 4),
        "VAL": round(val, 4)
    }
    return symbol, advice, details


async def send_telegram_message(session, symbol, advice, details):
    """Send a Telegram alert with Markdown formatting."""
    message = (
        "*Trade Alert!*\n\n"
        f"*Symbol:* _{symbol}_\n"
        f"*Trade Advice:* _{advice}_\n"
        f"*ENTRY:* _{details['Entry']}_\n"
        f"*SL:* _{details['SL']}_\n"
        f"*TP:* _{details['TP']}_\n\n"
        "*DATA DETAILS*\n"
        f"*POC:* _{details['POC']}_\n"
        f"*VAH:* _{details['VAH']}_\n"
        f"*VAL:* _{details['VAL']}_"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        async with session.post(url, data=params) as response:
            if response.status == 200:
                logging.info(f"[{symbol}] Telegram message sent.")
            else:
                logging.error(f"[{symbol}] Telegram send failed. Status: {response.status}")
    except Exception as e:
        logging.error(f"[{symbol}] Telegram Exception: {e}")


async def scan_symbols():
    """Main scanning loop using aiohttp and asyncio."""
    semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
    async with aiohttp.ClientSession() as session:
        while True:
            start_scan = time.time()
            tasks = []
            # Create tasks for each symbol with concurrency limit
            for symbol in SYMBOLS:
                async def sem_task(sym=symbol):
                    async with semaphore:
                        sym_ret, data = await fetch_binance_data(session, sym)
                        tick = await get_tick_size(session, sym)
                        return await calculate_trade_advice(sym_ret, data, tick)

                tasks.append(sem_task())
            try:
                trade_results = await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                logging.error(f"Error gathering trade results: {e}")
                trade_results = []

            for result in trade_results:
                # If an exception was returned, skip that symbol
                if isinstance(result, Exception) or result is None:
                    continue
                symbol, advice, details = result
                if details is None:
                    continue  # Skip if details are missing
                logging.info(
                    f"[{symbol}] Advice: {advice}, Entry: {details['Entry']}, TP: {details['TP']}, SL: {details['SL']}")
                if advice != "WAIT" and last_trade_advice.get(symbol) != advice:
                    await send_telegram_message(session, symbol, advice, details)
                    last_trade_advice[symbol] = advice
            logging.info(f"Scan completed in {time.time() - start_scan:.2f} seconds.")
            await asyncio.sleep(SCAN_INTERVAL)


async def main():
    try:
        await scan_symbols()
    except Exception as e:
        logging.error(f"Fatal error in main: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.error(f"Error running main loop: {e}")
