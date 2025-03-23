import sys
import asyncio
import pandas as pd
import numpy as np
import math
import requests
from datetime import datetime, time
import time as t
import logging
from binance import AsyncClient

# Configure logging.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Use WindowsSelectorEventLoopPolicy on Windows to avoid socket shutdown errors.
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

# Global dictionary to track last trade advice per symbol
last_trade_advice = {}


# --- Async Utility Functions ---
async def async_get_tick_size(symbol: str, client: AsyncClient) -> float:
    try:
        exchange_info = await client.get_exchange_info()
        for s in exchange_info["symbols"]:
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    if f["filterType"] == "PRICE_FILTER":
                        tick = float(f["tickSize"])
                        logger.info(f"[{symbol:<10}] Tick size: {tick}")
                        return tick
        logger.info(f"[{symbol:<10}] Tick size not found, using default 0.0001")
    except Exception as e:
        logger.error(f"[{symbol:<10}] Exception in async_get_tick_size: {e}")
    return 0.0001


async def async_auto_calculate_bin_size(symbol: str, price_min: float, price_max: float, client: AsyncClient,
                                        desired_bins: int = 50) -> float:
    try:
        price_range = price_max - price_min
        raw_bin_size = price_range / desired_bins
        tick_size = await async_get_tick_size(symbol, client)
        factor = math.ceil(raw_bin_size / tick_size)
        bin_size = factor * tick_size
        logger.info(
            f"[{symbol:<10}] Price range: {price_range}, Raw bin size: {raw_bin_size}, Calculated bin size: {bin_size}")
        return bin_size
    except Exception as e:
        logger.error(f"[{symbol:<10}] Exception in async_auto_calculate_bin_size: {e}")
        return 0.0


async def async_fetch_binance_data(symbol: str, client: AsyncClient, interval: str = DEFAULT_INTERVAL,
                                   start_time: datetime = None, end_time: datetime = None) -> pd.DataFrame:
    try:
        now = datetime.utcnow()
        if start_time is None:
            start_time = datetime.combine(now.date(), time(0, 0))
        if end_time is None:
            end_time = now
        start_str = start_time.strftime("%d %b %Y %H:%M:%S")
        end_str = end_time.strftime("%d %b %Y %H:%M:%S")
        logger.info(f"[{symbol:<10}] Fetching data from {start_str} to {end_str}")
        klines = await client.get_historical_klines(symbol, interval, start_str, end_str)
        if not klines:
            raise ValueError(f"No data returned for {symbol}")
        columns = ["OpenTime", "Open", "High", "Low", "Close", "Volume",
                   "CloseTime", "QuoteAssetVolume", "NumberOfTrades",
                   "TakerBuyBaseAssetVolume", "TakerBuyQuoteAssetVolume", "Ignore"]
        df = pd.DataFrame(klines, columns=columns)
        df["OpenTime"] = pd.to_datetime(df["OpenTime"], unit="ms")
        df["CloseTime"] = pd.to_datetime(df["CloseTime"], unit="ms")
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        logger.info(f"[{symbol:<10}] Fetched {len(df)} rows.")
        return df[["OpenTime", "Open", "High", "Low", "Close", "Volume"]]
    except Exception as e:
        logger.error(f"[{symbol:<10}] Exception in async_fetch_binance_data: {e}")
        return None


# --- Volume Profile Calculator (unchanged) ---
class VolumeProfileCalculator:
    def __init__(self, df: pd.DataFrame, bin_size: float, symbol: str):
        self.df = df
        self.bin_size = bin_size
        self.symbol = symbol
        self.profile = None

    def compute_profile(self):
        try:
            price_min = float(self.df["Low"].min())
            price_max = float(self.df["High"].max())
            bins = np.arange(price_min, price_max + self.bin_size, self.bin_size)
            bin_labels = (bins[:-1] + bins[1:]) / 2
            profile_df = pd.DataFrame({"Price": bin_labels, "Volume": 0.0})
            for _, row in self.df.iterrows():
                valid_bins = profile_df[
                    (profile_df["Price"] >= row["Low"]) & (profile_df["Price"] <= row["High"])].index
                if len(valid_bins) > 0:
                    distributed_volume = row["Volume"] / len(valid_bins)
                    profile_df.loc[valid_bins, "Volume"] += distributed_volume
            self.profile = profile_df
            logger.info(f"[{self.symbol:<10}] Volume profile computed.")
            return profile_df
        except Exception as e:
            logger.error(f"[{self.symbol:<10}] Exception in compute_profile: {e}")
            return None

    def calculate_poc(self):
        try:
            if self.profile is None:
                self.compute_profile()
            poc_row = self.profile.loc[self.profile["Volume"].idxmax()]
            logger.info(f"[{self.symbol:<10}] POC: {poc_row['Price']}")
            return poc_row["Price"]
        except Exception as e:
            logger.error(f"[{self.symbol:<10}] Exception in calculate_poc: {e}")
            return None

    def calculate_value_area(self, value_area_percent: float = 0.7):
        try:
            if self.profile is None:
                self.compute_profile()
            total_volume = self.profile["Volume"].sum()
            target_volume = total_volume * value_area_percent
            poc_index = self.profile["Volume"].idxmax()
            selected = {poc_index}
            cum_volume = self.profile.loc[poc_index, "Volume"]
            left = poc_index - 1
            right = poc_index + 1
            while cum_volume < target_volume:
                vol_left = self.profile.loc[left, "Volume"] if left >= 0 else 0
                vol_right = self.profile.loc[right, "Volume"] if right < len(self.profile) else 0
                if vol_left >= vol_right:
                    if left >= 0:
                        selected.add(left)
                        cum_volume += vol_left
                        left -= 1
                    elif right < len(self.profile):
                        selected.add(right)
                        cum_volume += vol_right
                        right += 1
                    else:
                        break
                else:
                    if right < len(self.profile):
                        selected.add(right)
                        cum_volume += vol_right
                        right += 1
                    elif left >= 0:
                        selected.add(left)
                        cum_volume += vol_left
                        left -= 1
                    else:
                        break
            selected_bins = self.profile.loc[list(selected)]
            value_area_high = selected_bins["Price"].max()
            value_area_low = selected_bins["Price"].min()
            logger.info(f"[{self.symbol:<10}] VAH: {value_area_high}, VAL: {value_area_low}")
            return value_area_high, value_area_low
        except Exception as e:
            logger.error(f"[{self.symbol:<10}] Exception in calculate_value_area: {e}")
            return None, None


# --- Telegram Message Sender ---
def send_telegram_message(message: str, token: str, chat_id: str):
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        r = requests.post(url, data=payload)
        if r.status_code == 200:
            logger.info("Telegram message sent successfully.")
        else:
            logger.error("Failed to send Telegram message. Status code: %s", r.status_code)
    except Exception as e:
        logger.error("Exception while sending Telegram message: %s", e)


# --- Asynchronous Scanner Function for a Single Symbol ---
async def async_scan_symbol(symbol: str, client: AsyncClient, interval: str = DEFAULT_INTERVAL) -> dict:
    try:
        logger.info(f"[{symbol:<10}] Starting scan...")
        data = await async_fetch_binance_data(symbol, client, interval)
        if data is None:
            logger.info(f"[{symbol:<10}] No data returned.")
            return None

        try:
            ticker = await client.get_symbol_ticker(symbol=symbol)
            current_price = float(ticker["price"])
        except Exception as e:
            logger.error(f"[{symbol:<10}] Exception getting ticker: {e}")
            return None

        price_min = float(data["Low"].min())
        price_max = float(data["High"].max())
        bin_size = await async_auto_calculate_bin_size(symbol, price_min, price_max, client, desired_bins=50)
        vp_calculator = VolumeProfileCalculator(data, bin_size=bin_size, symbol=symbol)
        vp_calculator.compute_profile()
        poc = vp_calculator.calculate_poc()
        vah, val = vp_calculator.calculate_value_area(value_area_percent=0.7)
        if None in (poc, vah, val):
            logger.info(f"[{symbol:<10}] Incomplete volume profile data.")
            return None

        poc_pct = ((poc - val) / (vah - val)) * 100 if (vah - val) != 0 else 0.0

        # Round values to 4 decimals.
        current_price_r = round(current_price, 4)
        poc_r = round(poc, 4)
        vah_r = round(vah, 4)
        val_r = round(val, 4)
        poc_pct_r = round(poc_pct, 4)

        # --- Trade Advice Logic ---
        trade_advice = "WAIT"
        if poc_pct < 30:
            if current_price >= val and current_price <= poc:
                trade_advice = "BUY"
            elif current_price < val and current_price <= poc:
                trade_advice = "LIKELY BUY"
        elif poc_pct > 70:
            if current_price >= poc and current_price <= vah:
                trade_advice = "SELL"
            elif current_price >= poc and current_price > vah:
                trade_advice = "LIKELY SELL"

        result = {
            "symbol": symbol,
            "current_price": current_price_r,
            "POC": poc_r,
            "VAH": vah_r,
            "VAL": val_r,
            "POC_pct": poc_pct_r,
            "trade_advice": trade_advice,
        }
        logger.info(f"[{symbol:<10}] Scan result: {result}")
        return result
    except Exception as e:
        logger.error(f"[{symbol:<10}] Exception in async_scan_symbol: {e}")
        return None


# --- Asynchronous Main Scanner Loop with Batching ---
async def async_main():
    global last_trade_advice
    for sym in SYMBOLS:
        last_trade_advice[sym] = None

    client = await AsyncClient.create()
    BATCH_SIZE = 5  # Process 5 symbols per batch
    try:
        while True:
            summary = []
            for i in range(0, len(SYMBOLS), BATCH_SIZE):
                batch = SYMBOLS[i:i + BATCH_SIZE]
                tasks = [async_scan_symbol(sym, client, DEFAULT_INTERVAL) for sym in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for res in results:
                    if isinstance(res, Exception):
                        logger.error("Error in one of the tasks: %s", res)
                    elif res:
                        summary.append(res)
                        symbol = res["symbol"]
                        advice = res["trade_advice"]
                        # --- Calculate Stop Loss using RR 1:2 ---
                        if advice != "WAIT" and advice != last_trade_advice[symbol]:
                            tick = await async_get_tick_size(symbol, client)
                            entry = res["current_price"]
                            if advice in ["BUY", "LIKELY BUY"]:
                                TP = res["VAH"]
                                risk = ((TP - entry) / tick) / 2 * tick
                                SL = entry - risk
                            elif advice in ["SELL", "LIKELY SELL"]:
                                TP = res["VAL"]
                                risk = ((entry - TP) / tick) / 2 * tick
                                SL = entry + risk
                            else:
                                TP = SL = 0.0
                            SL = round(SL, 4)
                            TP = round(TP, 4)
                            message = (
                                "*Trade Alert!*\n\n"
                                f"*Symbol:* _{symbol}_\n"
                                f"*Trade Advice:* _{advice}_\n"
                                f"*ENTRY:* _{entry}_\n"
                                f"*SL:* _{SL}_\n"
                                f"*TP:* _{TP}_\n\n"
                                "*DATA DETAILS*\n"
                                f"*POC:* _{res['POC']}_\n"
                                f"*VAH:* _{res['VAH']}_\n"
                                f"*VAL:* _{res['VAL']}_\n"
                                f"*POC %:* _{res['POC_pct']}%_\n\n"
                                f"-----------------------\n"
                                f"PLOT VD: [{res['POC']}, {res['VAH']},{res['VAL']}]\n"
                                f"PLOT TD: [{entry}, {SL},{TP}]\n"
                                f"-----------------------"
                            )
                            send_telegram_message(message, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
                            last_trade_advice[symbol] = advice
            logger.info("\n--- Scanner Summary (%s) ---", datetime.utcnow().strftime("%d %b %Y %H:%M:%S UTC"))
            for res in summary:
                if res['trade_advice'] != "WAIT":
                    logger.info(
                        f"{res['symbol']:<10}: Current Price: {res['current_price']}, POC: {res['POC']}, "
                        f"VAH: {res['VAH']}, VAL: {res['VAL']}, POC %: {res['POC_pct']}%, "
                        f"Trade Advice: {res['trade_advice']}"
                    )

            async def wait(seconds=60):
                start = seconds
                while start > 0:
                    print(f"\rCooling {start}s...", end="")
                    await asyncio.sleep(1)  # Non-blocking sleep
                    start -= 1
                logger.info("Cooling complete!")

            await wait(60)
    finally:
        await client.close_connection()


if __name__ == '__main__':
    asyncio.run(async_main())
