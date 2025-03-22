'''

bybit (buybit trader python)
api key: gC3vsCL2dXV66CZwI7
secret: Jsl17QH0LYFne8I4zlMnTLVriXvyyK5pQNiP
'''

import time
import json
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from typing import Tuple

class BybitTrader:
    def __init__(self, api_key, api_secret, base_url="https://api.bybit.com"):
        self.api_key = api_key
        self.api_secret = api_secret.encode('utf-8')
        self.base_url = base_url
        self.time_offset = 0

    def _sync_server_time(self) -> int:
        endpoint = "/v5/market/time"
        try:
            response = requests.get(self.base_url + endpoint, timeout=5)
            response.raise_for_status()
            data = response.json()
            server_time = int(data.get("result", {}).get("timeNano", 0)) // 1000000
            local_time = int(time.time() * 1000)
            self.time_offset = server_time - local_time
            return server_time
        except Exception as e:
            print(f"Error syncing server time: {e}")
            return int(time.time() * 1000)

    def _generate_signature(self, params: dict) -> str:
        formatted_params = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in params.items()}
        ordered_params = urlencode(sorted(formatted_params.items()))
        print(f"Signing string: {ordered_params}")
        signature = hmac.new(self.api_secret, ordered_params.encode('utf-8'), hashlib.sha256).hexdigest()
        print(f"Generated signature: {signature}")
        return signature

    def _send_request(self, endpoint: str, method: str = "GET", params: dict = None) -> dict:
        if params is None:
            params = {}

        if not endpoint.startswith("/v5/market") and not endpoint.startswith("/v5/public"):
            timestamp = str(self._sync_server_time() - 1000)
            params.update({
                "api_key": self.api_key,
                "timestamp": timestamp,
                "recv_window": "5000"
            })
            params["sign"] = self._generate_signature(params)

        url = self.base_url + endpoint

        try:
            if method.upper() == "GET":
                response = requests.get(url, params=params, timeout=10)
            else:
                headers = {"Content-Type": "application/json"}
                print(f"Request params: {params}")
                response = requests.post(url, json=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("retCode", 0) != 0:
                raise Exception(f"API error: {data.get('retMsg', 'Unknown error')}")
            return data
        except Exception as e:
            print(f"Request error: {e}")
            return {}

    def get_market_price(self, symbol: str) -> float:
        endpoint = "/v5/market/tickers"
        params = {"category": "linear", "symbol": symbol}
        data = self._send_request(endpoint, method="GET", params=params)
        try:
            result = data.get("result", {})
            tickers = result.get("list", [])
            if tickers:
                return float(tickers[0]["lastPrice"])
            raise Exception(f"No ticker data found for {symbol}")
        except (KeyError, IndexError, ValueError) as e:
            print(f"Error parsing market price: {e}")
        return 0.0

    def get_symbol_info(self, symbol: str) -> Tuple[float, float]:
        endpoint = "/v5/market/instruments-info"
        params = {"category": "linear", "symbol": symbol}
        data = self._send_request(endpoint, method="GET", params=params)
        try:
            result = data.get("result", {})
            instruments = result.get("list", [])
            if instruments:
                max_leverage = float(instruments[0]["leverageFilter"]["maxLeverage"])
                qty_step = float(instruments[0]["lotSizeFilter"]["qtyStep"])
                return max_leverage, qty_step
            raise Exception(f"Symbol {symbol} not found in instruments info.")
        except Exception as e:
            print(f"Error retrieving symbol info: {e}")
            return 0.0, 0.001

    def get_position_size(self, symbol: str, side: str) -> float:
        endpoint = "/v5/position/list"
        params = {"category": "linear", "symbol": symbol}
        data = self._send_request(endpoint, method="GET", params=params)
        try:
            result = data.get("result", {}).get("list", [])
            for pos in result:
                if pos["side"] == side:
                    return float(pos["size"])
            return 0.0
        except Exception as e:
            print(f"Error retrieving position size: {e}")
            return 0.0

    def get_position_mode(self, symbol: str) -> str:
        return "3"  # Hedge Mode confirmed manually

    def place_trade(self, signal: dict) -> dict:
        symbol = signal.get("symbol")
        trade_advice = signal.get("trade_advice", "").upper()
        stop_loss = signal.get("stop_loss")
        take_profit = signal.get("take_profit")

        if trade_advice not in ["BUY", "SELL"]:
            raise ValueError("trade_advice must be either 'BUY' or 'SELL'")

        side = "Buy" if trade_advice == "BUY" else "Sell"

        current_price = self.get_market_price(symbol)
        if current_price <= 0:
            raise Exception("Invalid market price retrieved.")

        max_leverage, qty_step = self.get_symbol_info(symbol)
        if max_leverage <= 0:
            raise Exception("Invalid max leverage retrieved.")

        order_value = max_leverage * 1.0
        raw_qty = order_value / current_price
        qty = round(raw_qty / qty_step) * qty_step
        qty = "{:.3f}".format(qty)

        position_size = self.get_position_size(symbol, side)
        position_mode = self.get_position_mode(symbol)
        print(f"Current {side} position size: {position_size}")
        print(f"Position mode: {position_mode} (0=One-Way, 3=Hedge)")

        order_params = {
            "category": "linear",
            "symbol": symbol,
            "side": side,
            "orderType": "Market",
            "qty": qty,
            "timeInForce": "GoodTillCancel",
            "reduceOnly": False,  # Changed to boolean False
            "positionIdx": 0 if side == "Buy" else 1  # Hedge Mode: 0 for Buy, 1 for Sell
        }

        if stop_loss:
            order_params["stopLoss"] = str(stop_loss)
        if take_profit:
            order_params["takeProfit"] = str(take_profit)

        endpoint = "/v5/order/create"
        response = self._send_request(endpoint, method="POST", params=order_params)
        return response

# Example usage:
if __name__ == "__main__":
    API_KEY = "gC3vsCL2dXV66CZwI7"
    API_SECRET = "Jsl17QH0LYFne8I4zlMnTLVriXvyyK5pQNiP"

    trader = BybitTrader(api_key=API_KEY, api_secret=API_SECRET)

    signal = {
        "symbol": "ARUSDT",
        "trade_advice": "SELL",
        "entry": "market",
        "stop_loss": 6.7125,
        "take_profit": 6.795
    }

    try:
        result = trader.place_trade(signal)
        print("Trade response:", json.dumps(result, indent=2))
    except Exception as e:
        print("Error placing trade:", e)