import csv
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, time as dtime
from typing import Any, Dict, List, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - for older Python
    from backports.zoneinfo import ZoneInfo  # type: ignore

import webview

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
PRODUCTS_CSV = os.path.join(DATA_DIR, "products.csv")
TIMEZONE = ZoneInfo("Asia/Singapore")
DEFAULT_PROVIDERS = ["fundgz", "aniu"]
DEFAULT_TIMEOUT_S = 3


@dataclass
class ProviderResult:
    intraday_pct: Optional[float]
    asof_time: Optional[datetime]
    source_url: str
    meta: Dict[str, Any]


@dataclass
class ProductConfig:
    code: str
    name: str
    kind: str
    mode: str
    ref: Dict[str, str]
    enabled: bool


class FundBoardAPI:
    def refresh(self) -> List[Dict[str, Any]]:
        products = load_products(PRODUCTS_CSV)
        results: List[Dict[str, Any]] = []
        now = datetime.now(TIMEZONE)

        for product in products:
            providers = parse_providers(product.ref.get("providers"))
            stale_rule = product.ref.get("stale_rule", "auto")
            timeout_s = parse_timeout(product.ref.get("timeout_s"), DEFAULT_TIMEOUT_S)
            last_error = ""
            last_provider = providers[-1] if providers else "fundgz"
            last_url = ""
            last_meta: Dict[str, Any] = {}
            last_asof: Optional[datetime] = None

            for provider in providers:
                try:
                    if provider == "fundgz":
                        result = fetch_fundgz(product.code, timeout_s)
                    elif provider == "aniu":
                        result = fetch_aniu(product.code, timeout_s)
                    else:
                        raise ValueError(f"unsupported provider: {provider}")

                    last_provider = provider
                    last_url = result.source_url
                    last_meta = result.meta
                    last_asof = result.asof_time

                    stale, stale_reason = is_stale(result.asof_time, now, stale_rule)
                    if stale:
                        last_error = f"stale: {stale_reason}"
                        continue

                    results.append(
                        build_result(
                            product,
                            result,
                            provider,
                            status="ok",
                            error="",
                        )
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    last_provider = provider
                    last_url = last_url or provider_url(provider, product.code)
                    last_meta = last_meta or {}
                    last_asof = last_asof or None
            else:
                status = "na" if last_error.startswith("stale") else "error"
                results.append(
                    {
                        "code": product.code,
                        "name": product.name,
                        "kind": product.kind,
                        "intraday_pct": None,
                        "status": status,
                        "error": last_error,
                        "source_mode": "fund_intraday",
                        "source_provider": last_provider,
                        "source_url": last_url,
                        "asof_time": format_time(last_asof or now),
                        "meta": last_meta,
                    }
                )

        return results


def load_products(path: str) -> List[ProductConfig]:
    products: List[ProductConfig] = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            enabled = row.get("enabled", "1").strip() == "1"
            if not enabled:
                continue
            products.append(
                ProductConfig(
                    code=row.get("code", "").strip(),
                    name=row.get("name", "").strip(),
                    kind=row.get("kind", "").strip(),
                    mode=row.get("mode", "").strip(),
                    ref=parse_ref(row.get("ref", "")),
                    enabled=enabled,
                )
            )
    return products


def parse_ref(ref: str) -> Dict[str, str]:
    if not ref:
        return {}
    result: Dict[str, str] = {}
    for part in ref.split(";"):
        if not part.strip():
            continue
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def parse_providers(value: Optional[str]) -> List[str]:
    if not value:
        return DEFAULT_PROVIDERS
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_timeout(value: Optional[str], default: int) -> int:
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def provider_url(provider: str, code: str) -> str:
    if provider == "fundgz":
        return fundgz_url(code)
    if provider == "aniu":
        return aniu_url(code)
    return ""


def fetch_fundgz(code: str, timeout_s: int) -> ProviderResult:
    url = fundgz_url(code)
    raw = fetch_text(url, timeout_s)
    payload = extract_jsonp(raw)
    data = json.loads(payload)
    pct = parse_float(data.get("gszzl"))
    asof = parse_time(data.get("gztime"))
    return ProviderResult(
        intraday_pct=pct,
        asof_time=asof,
        source_url=url,
        meta={
            "provider": "fundgz",
            "gztime": data.get("gztime"),
            "est_date": data.get("jzrq"),
            "raw_text": raw[:200],
        },
    )


def fetch_aniu(code: str, timeout_s: int) -> ProviderResult:
    candidates = [
        f"https://www.aniu.com/fund/valuation/{code}.json",
        f"https://www.aniu.com/fund/valuation/{code}",
    ]
    last_error: Optional[Exception] = None
    for url in candidates:
        try:
            raw = fetch_text(url, timeout_s)
            pct, asof = parse_aniu_payload(raw)
            if pct is None:
                raise ValueError("aniu payload missing intraday_pct")
            return ProviderResult(
                intraday_pct=pct,
                asof_time=asof,
                source_url=url,
                meta={
                    "provider": "aniu",
                    "raw_text": raw[:200],
                },
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
    raise ValueError(f"aniu failed: {last_error}")


def parse_aniu_payload(raw: str) -> tuple[Optional[float], Optional[datetime]]:
    raw = raw.strip()
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            pct = parse_float(
                data.get("gszzl")
                or data.get("gzzl")
                or data.get("estimate_rate")
                or data.get("estimateRate")
            )
            asof = parse_time(data.get("gztime") or data.get("time"))
            return pct, asof
        except json.JSONDecodeError:
            pass

    pct = None
    asof = None
    patterns = [
        r"\"gszzl\"\s*:\s*\"(?P<pct>[+-]?[0-9.]+)\"",
        r"\"gzzl\"\s*:\s*\"(?P<pct>[+-]?[0-9.]+)\"",
        r"\"estimate_rate\"\s*:\s*\"(?P<pct>[+-]?[0-9.]+)\"",
        r"\"estimateRate\"\s*:\s*\"(?P<pct>[+-]?[0-9.]+)\"",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            pct = parse_float(match.group("pct"))
            break

    time_match = re.search(r"\"gztime\"\s*:\s*\"(?P<time>[^\"]+)\"", raw)
    if not time_match:
        time_match = re.search(r"\"time\"\s*:\s*\"(?P<time>[^\"]+)\"", raw)
    if time_match:
        asof = parse_time(time_match.group("time"))

    return pct, asof


def fetch_text(url: str, timeout_s: int) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        data = response.read()
    return data.decode("utf-8", errors="ignore")


def extract_jsonp(raw: str) -> str:
    match = re.search(r"\((\{.*\})\)", raw)
    if not match:
        raise ValueError("invalid fundgz response")
    return match.group(1)


def parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=TIMEZONE)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value).replace(tzinfo=TIMEZONE)
    except ValueError:
        return None


def format_time(value: datetime) -> str:
    return value.astimezone(TIMEZONE).isoformat(timespec="seconds")


def is_stale(asof: Optional[datetime], now: datetime, rule: str) -> tuple[bool, str]:
    if not asof:
        return True, "missing asof_time"
    if asof.date() != now.date():
        return True, "date mismatch"

    max_age_minutes = 5 if rule == "strict" else 15
    if in_trading_hours(now):
        age = (now - asof).total_seconds() / 60
        if age > max_age_minutes:
            return True, f"age {age:.1f}m"

    return False, ""


def in_trading_hours(now: datetime) -> bool:
    current = now.time()
    morning_start = dtime(9, 30)
    morning_end = dtime(11, 30)
    afternoon_start = dtime(13, 0)
    afternoon_end = dtime(15, 0)
    return (morning_start <= current <= morning_end) or (
        afternoon_start <= current <= afternoon_end
    )


def build_result(
    product: ProductConfig,
    result: ProviderResult,
    provider: str,
    status: str,
    error: str,
) -> Dict[str, Any]:
    return {
        "code": product.code,
        "name": product.name,
        "kind": product.kind,
        "intraday_pct": result.intraday_pct,
        "status": status,
        "error": error,
        "source_mode": "fund_intraday",
        "source_provider": provider,
        "source_url": result.source_url,
        "asof_time": format_time(result.asof_time or datetime.now(TIMEZONE)),
        "meta": result.meta,
    }


def fundgz_url(code: str) -> str:
    return f"http://fundgz.1234567.com.cn/js/{code}.js?rt={int(time.time() * 1000)}"


def aniu_url(code: str) -> str:
    return f"https://www.aniu.com/fund/valuation/{code}"


def load_html() -> str:
    path = os.path.join(WEB_DIR, "index.html")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def main() -> None:
    api = FundBoardAPI()
    window = webview.create_window(
        "盘中涨跌看板",
        html=load_html(),
        width=1080,
        height=720,
        js_api=api,
    )
    webview.start(debug=True)


if __name__ == "__main__":
    main()
