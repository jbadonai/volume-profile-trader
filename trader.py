# --- Telegram Settings ---
TELEGRAM_BOT_TOKEN = "7670784421:AAEL2j8knz5Klg1kzRx-HAJpCllbzEux28Q"
TELEGRAM_CHAT_ID = "6590880408"

import asyncio
import pandas as pd
import numpy as np
import math
import requests
from binance.client import Client
from datetime import datetime, time
import time as t
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Telegram Settings ---
TELEGRAM_BOT_TOKEN = "7670784421:AAEL2j8knz5Klg1kzRx-HAJpCllbzEux28Q"
TELEGRAM_CHAT_ID = "6590880408"

# --- Default Scanner Settings ---
DEFAULT_INTERVAL = "5m"
SYMBOLS = ['DOTUSDT', 'ADAUSDT', '1INCHUSDT', "XRPUSDT", "ARUSDT"]

# Global dictionary to track last trade advice per symbol
last_trade_advice = {}

# --- Utility to Auto-Calculate Bin Size ---
def get_tick_size(symbol: str) -> float:
    try:
        client = Client("", "")
        exchange_info = client.get_exchange_info()
        for s in exchange_info["symbols"]:
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    if f["filterType"] == "PRICE_FILTER":
                        tick = float(f["tickSize"])
                        print(f"[{symbol}] Tick size: {tick}")
                        return tick
        print(f"[{symbol}] Tick size not found, using default 0.0001")
    except Exception as e:
        print(f"[{symbol}] Exception in get_tick_size: {e}")
    return 0.0001

def auto_calculate_bin_size(symbol: str, price_min: float, price_max: float, desired_bins: int = 50) -> float:
    try:
        price_range = price_max - price_min
        raw_bin_size = price_range / desired_bins
        tick_size = get_tick_size(symbol)
        factor = math.ceil(raw_bin_size / tick_size)
        bin_size = factor * tick_size
        print(f"[{symbol}] Price range: {price_range}, Raw bin size: {raw_bin_size}, Calculated bin size: {bin_size}")
        return bin_size
    except Exception as e:
        print(f"[{symbol}] Exception in auto_calculate_bin_size: {e}")
        return 0.0

# --- Data Retrieval from Binance (public endpoints) ---
def fetch_binance_data(symbol: str, interval: str = DEFAULT_INTERVAL, start_time: datetime = None, end_time: datetime = None):
    try:
        client = Client("", "")
        now = datetime.utcnow()
        if start_time is None:
            start_time = datetime.combine(now.date(), time(0, 0))
        if end_time is None:
            end_time = now

        start_str = start_time.strftime("%d %b %Y %H:%M:%S")
        end_str = end_time.strftime("%d %b %Y %H:%M:%S")
        print(f"[{symbol}] Fetching data from {start_str} to {end_str}")
        klines = client.get_historical_klines(symbol, interval, start_str, end_str)
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
        print(f"[{symbol}] Fetched {len(df)} rows.")
        return df[["OpenTime", "Open", "High", "Low", "Close", "Volume"]]
    except Exception as e:
        print(f"[{symbol}] Exception in fetch_binance_data: {e}")
        return None

# --- Volume Profile Calculator ---
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
                valid_bins = profile_df[(profile_df["Price"] >= row["Low"]) & (profile_df["Price"] <= row["High"])].index
                if len(valid_bins) > 0:
                    distributed_volume = row["Volume"] / len(valid_bins)
                    profile_df.loc[valid_bins, "Volume"] += distributed_volume
            self.profile = profile_df
            print(f"[{self.symbol}] Volume profile computed.")
            return profile_df
        except Exception as e:
            print(f"[{self.symbol}] Exception in compute_profile: {e}")
            return None

    def calculate_poc(self):
        try:
            if self.profile is None:
                self.compute_profile()
            poc_row = self.profile.loc[self.profile["Volume"].idxmax()]
            print(f"[{self.symbol}] POC: {poc_row['Price']}")
            return poc_row["Price"]
        except Exception as e:
            print(f"[{self.symbol}] Exception in calculate_poc: {e}")
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
            print(f"[{self.symbol}] VAH: {value_area_high}, VAL: {value_area_low}")
            return value_area_high, value_area_low
        except Exception as e:
            print(f"[{self.symbol}] Exception in calculate_value_area: {e}")
            return None, None

# --- Telegram Message Sender ---
def send_telegram_message(message: str, token: str, chat_id: str):
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        r = requests.post(url, data=payload)
        if r.status_code == 200:
            print("Telegram message sent successfully.")
        else:
            print("Failed to send Telegram message. Status code:", r.status_code)
    except Exception as e:
        print("Exception while sending Telegram message:", e)

# --- Scanner Function for a Single Symbol ---
def scan_symbol(symbol: str, interval: str = DEFAULT_INTERVAL) -> dict:
    try:
        # Ensure each thread gets its own event loop.
        asyncio.set_event_loop(asyncio.new_event_loop())
        print(f"[{symbol}] Starting scan...")
        data = fetch_binance_data(symbol, interval)
        if data is None:
            print(f"[{symbol}] No data returned.")
            return None

        client = Client("", "")
        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            current_price = float(ticker["price"])
        except Exception as e:
            print(f"[{symbol}] Exception getting ticker: {e}")
            current_price = None

        if current_price is None:
            return None

        price_min = float(data["Low"].min())
        price_max = float(data["High"].max())
        bin_size = auto_calculate_bin_size(symbol, price_min, price_max, desired_bins=50)
        vp_calculator = VolumeProfileCalculator(data, bin_size=bin_size, symbol=symbol)
        vp_calculator.compute_profile()
        poc = vp_calculator.calculate_poc()
        vah, val = vp_calculator.calculate_value_area(value_area_percent=0.7)
        if None in (poc, vah, val):
            print(f"[{symbol}] Incomplete volume profile data.")
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
        print(f"[{symbol}] Scan result: {result}")
        return result
    except Exception as e:
        print(f"[{symbol}] Exception in scan_symbol: {e}")
        return None

# --- Main Scanner Loop ---
def main():
    global last_trade_advice
    # Initialize last_trade_advice for each symbol.
    for sym in SYMBOLS:
        last_trade_advice[sym] = None

    with ThreadPoolExecutor(max_workers=len(SYMBOLS)) as executor:
        while True:
            try:
                futures = {executor.submit(scan_symbol, sym, DEFAULT_INTERVAL): sym for sym in SYMBOLS}
                print("Futures:", futures)
                summary = []
                for future in as_completed(futures):
                    res = future.result()
                    if res:
                        summary.append(res)
                        symbol = res["symbol"]
                        advice = res["trade_advice"]
                        # Send Telegram alert if advice is not WAIT and has changed.
                        if advice != "WAIT" and advice != last_trade_advice[symbol]:
                            tick = get_tick_size(symbol)
                            entry = res["current_price"]
                            if advice in ["BUY", "LIKELY BUY"]:
                                TP = res["VAH"]  # target remains VAH for buy trades
                                # Calculate risk: number of ticks = (TP - entry) / tick
                                # Risk in ticks = (TP - entry) / tick / 2
                                risk = ((TP - entry) / tick) / 2 * tick  # convert back to price difference
                                SL = entry - risk
                            elif advice in ["SELL", "LIKELY SELL"]:
                                TP = res["VAL"]  # target remains VAL for sell trades
                                risk = ((entry - TP) / tick) / 2 * tick
                                SL = entry + risk
                            else:
                                entry = res["current_price"]
                                SL = TP = 0.0
                            # Round SL and TP to 4 decimals as well.
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
                                f"*POC %:* _{res['POC_pct']}%_"
                            )
                            send_telegram_message(message, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
                            last_trade_advice[symbol] = advice
                print("\n--- Scanner Summary (" + datetime.utcnow().strftime("%d %b %Y %H:%M:%S UTC") + ") ---")
                for res in summary:
                    print(
                        f"{res['symbol']}: Current Price: {res['current_price']}, POC: {res['POC']}, "
                        f"VAH: {res['VAH']}, VAL: {res['VAL']}, POC %: {res['POC_pct']}%, "
                        f"Trade Advice: {res['trade_advice']}"
                    )
            except Exception as e:
                print("Exception in main scanner loop:", e)

            # t.sleep(120)
            index = 120
            while True:
                index -= 1
                print(f"\rCooling down {index}...", end="")
                t.sleep(1)
                if index <= 0:
                    break

if __name__ == '__main__':
    main()
