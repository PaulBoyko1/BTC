from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.research.types import MarketType

from .types import Horizon, IntervalAnalysis


class PolymarketPublicAdapter:
    """Read-only Polymarket Gamma/CLOB adapter.

    Market discovery and order-book reads are public and do not require API keys.
    The adapter never submits orders and never requests wallet credentials.
    """

    gamma_root = "https://gamma-api.polymarket.com"
    clob_root = "https://clob.polymarket.com"

    def __init__(self, timeout_seconds: float = 6.0) -> None:
        self.timeout_seconds = timeout_seconds

    def _get_json(self, url: str) -> Any:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "crypto-interval-analyzer/2.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _json_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return []
            return parsed if isinstance(parsed, list) else []
        return []

    @staticmethod
    def _hourly_slug_candidates(start_timestamp: int) -> tuple[str, ...]:
        eastern = datetime.fromtimestamp(start_timestamp, tz=timezone.utc).astimezone(ZoneInfo("America/New_York"))
        month = eastern.strftime("%B").lower()
        hour = eastern.strftime("%I").lstrip("0") or "12"
        ampm = eastern.strftime("%p").lower()
        return (
            f"bitcoin-up-or-down-{month}-{eastern.day}-{eastern.year}-{hour}{ampm}-et",
            f"bitcoin-up-or-down-{month}-{eastern.day}-{hour}{ampm}-et",
        )

    @classmethod
    def slug_candidates(cls, asset: str, horizon: Horizon, start_timestamp: int) -> tuple[str, ...]:
        if horizon == Horizon.ONE_HOUR:
            return cls._hourly_slug_candidates(start_timestamp) if asset == "BTCUSDT" else ()
        prefix = {
            "BTCUSDT": "btc",
            "ETHUSDT": "eth",
            "SOLUSDT": "sol",
            "XRPUSDT": "xrp",
        }.get(asset)
        if prefix is None:
            return ()
        return (
            f"{prefix}-updown-15m-{start_timestamp}",
            f"{prefix}-up-or-down-15m-{start_timestamp}",
        )

    def _event(self, slug: str) -> dict[str, Any] | None:
        url = f"{self.gamma_root}/events/slug/{urllib.parse.quote(slug)}"
        try:
            payload = self._get_json(url)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _book(self, token_id: str) -> dict[str, Any] | None:
        query = urllib.parse.urlencode({"token_id": token_id})
        try:
            payload = self._get_json(f"{self.clob_root}/book?{query}")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _market_from_event(event: dict[str, Any]) -> dict[str, Any] | None:
        markets = event.get("markets")
        if isinstance(markets, list) and markets:
            dictionaries = [market for market in markets if isinstance(market, dict)]
            if not dictionaries:
                return None
            live = [market for market in dictionaries if bool(market.get("active", True)) and not bool(market.get("closed", False))]
            return live[0] if live else dictionaries[0]
        if event.get("clobTokenIds"):
            return event
        return None

    @staticmethod
    def _side_quote(token_id: str | None, book: dict[str, Any] | None, fallback_price: float | None) -> dict[str, Any]:
        bids = book.get("bids", []) if isinstance(book, dict) else []
        asks = book.get("asks", []) if isinstance(book, dict) else []

        def levels(rows: Any) -> list[tuple[float, float]]:
            output: list[tuple[float, float]] = []
            if not isinstance(rows, list):
                return output
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    output.append((float(row["price"]), float(row.get("size", 0.0))))
                except (KeyError, TypeError, ValueError):
                    continue
            return output

        bid_levels = levels(bids)
        ask_levels = levels(asks)
        best_bid = max(bid_levels, default=(None, None), key=lambda item: item[0])
        best_ask = min(ask_levels, default=(None, None), key=lambda item: item[0])
        bid = best_bid[0]
        ask = best_ask[0]
        midpoint = (bid + ask) / 2.0 if bid is not None and ask is not None else fallback_price
        last = None
        if isinstance(book, dict) and book.get("last_trade_price") is not None:
            try:
                last = float(book["last_trade_price"])
            except (TypeError, ValueError):
                last = None
        return {
            "token_id": token_id,
            "bid": bid,
            "ask": ask,
            "midpoint": midpoint,
            "last_trade": last,
            "bid_size": best_bid[1],
            "ask_size": best_ask[1],
            "fallback_price": fallback_price,
        }

    def current_quote(
        self,
        *,
        asset: str,
        horizon: Horizon,
        start_timestamp: int,
        expiry_timestamp: int,
    ) -> dict[str, Any]:
        errors: list[str] = []
        for slug in self.slug_candidates(asset, horizon, start_timestamp):
            event = self._event(slug)
            if event is None:
                errors.append(f"event not found for {slug}")
                continue
            market = self._market_from_event(event)
            if market is None:
                errors.append(f"event {slug} has no tradable market")
                continue
            outcomes = [str(value) for value in self._json_list(market.get("outcomes"))]
            token_ids = [str(value) for value in self._json_list(market.get("clobTokenIds"))]
            prices_raw = self._json_list(market.get("outcomePrices"))
            prices: list[float | None] = []
            for value in prices_raw:
                try:
                    prices.append(float(value))
                except (TypeError, ValueError):
                    prices.append(None)
            index_by_name = {name.strip().lower(): index for index, name in enumerate(outcomes)}
            up_index = index_by_name.get("up", index_by_name.get("yes"))
            down_index = index_by_name.get("down", index_by_name.get("no"))
            if up_index is None or down_index is None:
                errors.append(f"event {slug} outcomes are not Up/Down")
                continue

            def item_at(values: list[Any], index: int | None) -> Any:
                if index is None or index < 0 or index >= len(values):
                    return None
                return values[index]

            up_token = item_at(token_ids, up_index)
            down_token = item_at(token_ids, down_index)
            up_book = self._book(str(up_token)) if up_token else None
            down_book = self._book(str(down_token)) if down_token else None
            up_price = item_at(prices, up_index)
            down_price = item_at(prices, down_index)
            resolution_source = str(event.get("resolutionSource") or market.get("resolutionSource") or "Polymarket market rules")
            reference_mismatch = horizon == Horizon.FIFTEEN_MINUTES
            return {
                "provider": "polymarket",
                "available": True,
                "fetched_timestamp": int(time.time()),
                "asset": asset,
                "horizon": horizon.value,
                "interval_start_timestamp": start_timestamp,
                "expiry_timestamp": expiry_timestamp,
                "market_title": event.get("title") or market.get("question") or slug,
                "market_slug": slug,
                "market_url": f"https://polymarket.com/event/{slug}",
                "resolution_source": resolution_source,
                "reference_mismatch": reference_mismatch,
                "reference_warning": (
                    "The 15-minute Polymarket crypto contract resolves from a Chainlink price stream while this analyzer currently models Binance data. The displayed gap is therefore indicative, not a locked arbitrage."
                    if reference_mismatch
                    else "The hourly Polymarket BTC contract and this analyzer both use Binance BTC/USDT direction, subject to the exact market rules."
                ),
                "up": self._side_quote(str(up_token) if up_token else None, up_book, up_price),
                "down": self._side_quote(str(down_token) if down_token else None, down_book, down_price),
                "errors": errors,
            }
        return {
            "provider": "polymarket",
            "available": False,
            "fetched_timestamp": int(time.time()),
            "asset": asset,
            "horizon": horizon.value,
            "interval_start_timestamp": start_timestamp,
            "expiry_timestamp": expiry_timestamp,
            "market_title": None,
            "market_slug": None,
            "market_url": None,
            "resolution_source": None,
            "reference_mismatch": False,
            "reference_warning": "No matching live public contract was discovered. Manual prices can still be compared.",
            "up": self._side_quote(None, None, None),
            "down": self._side_quote(None, None, None),
            "errors": errors or ["no automatic contract mapping for this asset/horizon"],
        }


def indicative_probability(raw_score: float) -> float:
    """Convert a bounded research score to a display-only fair value.

    This is intentionally labelled uncalibrated. It exists to make score/market
    comparisons legible; it is not evidence that the forecast is accurate.
    """

    probability = 1.0 / (1.0 + math.exp(-3.6 * max(-1.0, min(1.0, raw_score))))
    return min(0.99, max(0.01, probability))


def _selected_price(side: dict[str, Any], manual_price: float | None) -> tuple[float | None, str]:
    if manual_price is not None:
        return manual_price, "manual"
    for key, source in (("ask", "best_ask"), ("midpoint", "midpoint"), ("fallback_price", "gamma_price"), ("last_trade", "last_trade")):
        value = side.get(key)
        if isinstance(value, (int, float)) and 0 < float(value) < 1:
            return float(value), source
    return None, "unavailable"


def _side_comparison(name: str, fair: float, side: dict[str, Any], manual_price: float | None) -> dict[str, Any]:
    price, price_source = _selected_price(side, manual_price)
    edge = fair - price if price is not None else None
    roi = edge / price if edge is not None and price is not None and price > 0 else None
    return {
        "side": name,
        "fair_value": fair,
        "market_price": price,
        "price_source": price_source,
        "edge": edge,
        "edge_cents": edge * 100.0 if edge is not None else None,
        "no_fee_expected_profit_per_share": edge,
        "no_fee_expected_roi": roi,
        "bid": side.get("bid"),
        "ask": side.get("ask"),
        "midpoint": side.get("midpoint"),
        "bid_size": side.get("bid_size"),
        "ask_size": side.get("ask_size"),
    }


def compare_contracts(
    analysis: IntervalAnalysis,
    quote: dict[str, Any],
    *,
    manual_up: float | None = None,
    manual_down: float | None = None,
) -> dict[str, Any]:
    if manual_up is not None and not 0 < manual_up < 1:
        raise ValueError("manual_up must be between 0 and 1")
    if manual_down is not None and not 0 < manual_down < 1:
        raise ValueError("manual_down must be between 0 and 1")
    calibrated = analysis.up_probability is not None and analysis.down_probability is not None
    fair_up = float(analysis.up_probability) if calibrated else indicative_probability(analysis.raw_direction_score)
    fair_down = 1.0 - fair_up
    up = _side_comparison("up", fair_up, dict(quote.get("up") or {}), manual_up)
    down = _side_comparison("down", fair_down, dict(quote.get("down") or {}), manual_down)
    candidates = [item for item in (up, down) if isinstance(item.get("edge"), (int, float))]
    best = max(candidates, key=lambda item: float(item["edge"])) if candidates else None
    return {
        "asset": analysis.asset,
        "market_type": analysis.market_type.value if isinstance(analysis.market_type, MarketType) else str(analysis.market_type),
        "horizon": analysis.horizon.value,
        "interval_start_timestamp": analysis.interval_start_timestamp,
        "expiry_timestamp": analysis.expiry_timestamp,
        "reference_price": analysis.reference_price,
        "current_price": analysis.current_price,
        "fair_value_state": "calibrated" if calibrated else "indicative_uncalibrated",
        "fair_value_label": "CALIBRATED MODEL FAIR VALUE" if calibrated else "INDICATIVE FAIR VALUE — NOT A VALIDATED PROBABILITY",
        "edge_label": "MODEL EDGE" if calibrated else "INDICATIVE GAP — NOT A VALIDATED EDGE",
        "up": up,
        "down": down,
        "best_side": best["side"] if best and float(best["edge"]) > 0 else None,
        "best_edge": float(best["edge"]) if best else None,
        "no_fee_assumption": True,
        "quote": quote,
        "no_trade_is_filter_only": True,
        "explanation": (
            "No Trade means the directional score did not clear the configured signal threshold. "
            "It does not change the fixed expiry and it does not prevent contract prices from being displayed."
        ),
    }
