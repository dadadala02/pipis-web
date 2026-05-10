#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import datetime as dt
import json
import os
import re
import statistics
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote_plus


def get_json(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def get_text(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/xml,text/xml,text/html,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def post_json(url: str, payload: dict, timeout: int = 45):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def to_float(text):
    if text is None:
        return None
    s = str(text).replace(",", "").strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def format_signed(value, digits=2):
    sign = "+" if value >= 0 else "-"
    return f"{sign}{abs(value):.{digits}f}"


def read_stock_codes(path):
    codes = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^(\d{4,6})", line)
        if match:
            codes.append(match.group(1))
    seen = set()
    unique_codes = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            unique_codes.append(code)
    return unique_codes


def get_quote_map(codes):
    query_parts = []
    for code in codes:
        query_parts.append(f"tse_{code}.tw")
        query_parts.append(f"otc_{code}.tw")
    url = (
        "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch="
        + "|".join(query_parts)
        + "&json=1&delay=0"
    )
    data = get_json(url)
    out = {}
    for item in data.get("msgArray", []):
        code = item.get("c", "")
        if not code:
            continue
        if code not in out and item.get("n"):
            out[code] = item
    return out


def get_yahoo_chart(symbol: str, range_text: str = "6mo"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={range_text}"
    data = get_json(url)
    result = data.get("chart", {}).get("result")
    if not result:
        return None
    result = result[0]
    timestamps = result.get("timestamp", [])
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    volumes = result.get("indicators", {}).get("quote", [{}])[0].get("volume", [])
    # Keep only rows where both close and volume are non-None
    valid = [(t, c, v) for t, c, v in zip(timestamps, closes, volumes) if c is not None and v is not None]
    return {
        "timestamp": [x[0] for x in valid],
        "close": [x[1] for x in valid],
        "volume": [x[2] for x in valid],
    }


def get_technical_stats(symbol: str):
    chart = get_yahoo_chart(symbol)
    if not chart or len(chart["close"]) < 60:
        return None
    closes = chart["close"]
    volumes = chart["volume"]
    timestamps = chart.get("timestamp", [])
    ma5 = statistics.mean(closes[-5:])
    ma20 = statistics.mean(closes[-20:])
    ma60 = statistics.mean(closes[-60:])
    high20 = max(closes[-20:])
    low20 = min(closes[-20:])
    vol5 = statistics.mean(volumes[-5:]) if len(volumes) >= 5 else None
    vol20 = statistics.mean(volumes[-20:]) if len(volumes) >= 20 else None
    vol_ratio = None
    if vol5 and vol20 and vol20 != 0:
        vol_ratio = vol5 / vol20
    # Recent 10 days for per-stock mini charts (convert shares → 張, 1張=1000股)
    n = min(10, len(closes))
    recent_closes = [round(c, 2) for c in closes[-n:]]
    recent_volumes = [round(v / 1000) for v in volumes[-n:]]  # shares → 張
    recent_dates = []
    if timestamps:
        for ts in timestamps[-n:]:
            d = dt.datetime.utcfromtimestamp(ts)
            recent_dates.append(f"{d.month:02d}/{d.day:02d}")
    else:
        recent_dates = [f"D-{n-1-i}" for i in range(n)]
    return {
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "high20": high20,
        "low20": low20,
        "vol_ratio": vol_ratio,
        "vol5_avg": vol5,
        "vol20_avg": vol20,
        "recent_closes": recent_closes,
        "recent_volumes": recent_volumes,
        "recent_dates": recent_dates,
    }


def get_news_headlines(query: str, limit: int = 3):
    try:
        from urllib.parse import quote_plus as qp
        q = qp(query)
        url = f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        raw = get_text(url)
        root = ET.fromstring(raw)
        items = root.findall(".//item/title")
        out = []
        for item in items[:limit]:
            title = (item.text or "").strip()
            if title:
                out.append(title)
        return out
    except Exception:
        return []


def discover_gemini_models(api_key: str):
    try:
        data = get_json(f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}")
        models = []
        for item in data.get("models", []):
            methods = item.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue
            name = str(item.get("name", ""))
            short_name = name.split("/")[-1] if "/" in name else name
            if short_name:
                models.append(short_name)
        models.sort(key=lambda x: ("flash" not in x.lower(), x))
        return models
    except Exception:
        return []


def get_candidate_models(api_key: str, preferred_model: str):
    discovered = discover_gemini_models(api_key)
    candidates = [preferred_model, "gemini-2.5-flash", "gemini-2.5-pro", *discovered]
    return list(dict.fromkeys(candidates))


def extract_gemini_text(payload: dict) -> str:
    try:
        candidates = payload.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        text_parts = [p.get("text", "") for p in parts if isinstance(p, dict)]
        return "\n".join([x for x in text_parts if x]).strip()
    except Exception:
        return ""


def request_gemini_text(prompt, api_key, candidate_models, max_output_tokens=1800, request_timeout=30, disable_thinking=False):
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.5, "maxOutputTokens": max_output_tokens},
    }
    if disable_thinking:
        payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
    last_error = ""
    for model_name in candidate_models:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
            f"?key={api_key}"
        )
        try:
            result = post_json(url, payload, timeout=request_timeout)
            text = extract_gemini_text(result)
            if text:
                return text.strip(), ""
            last_error = f"模型 {model_name} 回傳空內容"
        except urllib.error.HTTPError as err:
            last_error = f"模型 {model_name} HTTP {err.code}"
            if err.code in (404, 400):
                continue
            return "", str(err)
        except Exception as err:
            last_error = str(err)
    return "", last_error


def generate_stock_advice(stock_info: dict, model: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "- 趨勢：未設定 GEMINI_API_KEY\n- 關鍵價位：N/A\n- 量價：N/A\n- 風險：N/A\n- 行動建議：N/A"
    candidate_models = get_candidate_models(api_key, model)[:3]
    prompt = (
        "你是台股分析師，請針對以下個股輸出五行繁體中文分析，"
        "格式嚴格如下（每行以「- 標籤：」開頭，不得省略任何一行）：\n\n"
        "- 趨勢：（趨勢方向，30字內）\n"
        "- 關鍵價位：（支撐與壓力區，30字內）\n"
        "- 量價：（量能與價格關係，30字內）\n"
        "- 風險：（主要風險，30字內）\n"
        "- 行動建議：（進出場建議，30字內）\n\n"
        "個股資料：\n"
        f"代碼={stock_info['code']} 名稱={stock_info['name']} 市場={stock_info['market']}\n"
        f"收盤={stock_info['close_text']} 開高低={stock_info['ohl_text']}\n"
        f"成交量={stock_info['volume_text']} 均線={stock_info['ma_text']}\n"
        f"區間={stock_info['range_text']} 量能比={stock_info['vol_ratio_text']}\n"
    )
    text, err = request_gemini_text(
        prompt, api_key, candidate_models,
        max_output_tokens=500, request_timeout=30, disable_thinking=True
    )
    if text:
        return text.strip()
    return f"- 趨勢：暫時無法產生（{err}）\n- 關鍵價位：N/A\n- 量價：N/A\n- 風險：N/A\n- 行動建議：N/A"


def generate_market_overview(date_text: str, stock_pairs, stock_info_map: dict, model: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "未設定 GEMINI_API_KEY，已略過大盤分析。"
    stocks_summary = "\n".join([
        f"- {code} {name}：收盤 {stock_info_map[code]['close_text']}，量能比 {stock_info_map[code]['vol_ratio_text']}，均線 {stock_info_map[code]['ma_text']}"
        for code, name in stock_pairs if code in stock_info_map
    ])
    prompt = f"""你是台股大盤走勢分析師。今日資料日期：{date_text}。
根據以下自選股今日資料，分析大盤走勢。請用繁體中文條列式輸出，約 150~200 字，包含：
- 整體市場方向
- 強弱股特徵
- 值得關注的市場現象

自選股今日資料：
{stocks_summary}
"""
    candidate_models = get_candidate_models(api_key, model)[:3]
    text, err = request_gemini_text(prompt, api_key, candidate_models, max_output_tokens=600, request_timeout=30, disable_thinking=True)
    if text:
        return text.strip()
    return f"大盤分析暫時無法產生（{err}）。"


def generate_overall_evaluation(date_text: str, stock_pairs, stock_info_map: dict, model: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "未設定 GEMINI_API_KEY，已略過綜合評價。"
    stocks_detail = "\n".join([
        f"- {code} {name}：收盤 {stock_info_map.get(code, {}).get('close_text', 'N/A')}，均線 {stock_info_map.get(code, {}).get('ma_text', 'N/A')}，量能比 {stock_info_map.get(code, {}).get('vol_ratio_text', 'N/A')}"
        for code, name in stock_pairs if code in stock_info_map
    ])
    prompt = f"""你是台股投資組合分析師。資料日期：{date_text}。
根據以下自選股資料，給出整體投資組合評估，用繁體中文條列式輸出，約 200~250 字，包含：

1. 整體強弱評估
2. 風險排序（由高到低，附一句原因）
3. 明日重點觀察（3~5 點）
4. 免責聲明（一句話）

自選股資料：
{stocks_detail}
"""
    candidate_models = get_candidate_models(api_key, model)[:3]
    text, err = request_gemini_text(prompt, api_key, candidate_models, max_output_tokens=900, request_timeout=35, disable_thinking=True)
    if text:
        return text.strip()
    return f"綜合評價暫時無法產生（{err}）。"


def build_stock_block(code: str, quote: dict, technical, headlines: list, advice: str) -> str:
    name = quote.get("n", "N/A")
    market = "上市" if quote.get("ex") == "tse" else "上櫃"
    last = to_float(quote.get("z") or quote.get("y"))
    prev = to_float(quote.get("y"))
    high = to_float(quote.get("h"))
    low = to_float(quote.get("l"))
    open_price = to_float(quote.get("o"))
    volume = to_float(quote.get("v"))
    diff = (last - prev) if (last is not None and prev is not None) else None
    pct = ((diff / prev) * 100) if (diff is not None and prev) else None

    # Build chart JSON payload (single-quote wrapper so double-quotes in JSON are safe)
    def _r(v, d=2): return round(v, d) if v is not None else None
    chart_payload = {
        "code": code,
        "name": name,
        "market": market,
        "close": _r(last),
        "change": _r(diff),
        "changePct": _r(pct),
        "open": _r(open_price),
        "high": _r(high),
        "low": _r(low),
        "volume": int(volume) if volume is not None else None,
        "ma5": _r(technical["ma5"]) if technical else None,
        "ma20": _r(technical["ma20"]) if technical else None,
        "ma60": _r(technical["ma60"]) if technical else None,
        "high20": _r(technical["high20"]) if technical else None,
        "low20": _r(technical["low20"]) if technical else None,
        "volRatio": _r(technical["vol_ratio"]) if technical and technical["vol_ratio"] is not None else None,
        "vol5avg": round(technical["vol5_avg"] / 1000) if technical and technical.get("vol5_avg") is not None else None,
        "vol20avg": round(technical["vol20_avg"] / 1000) if technical and technical.get("vol20_avg") is not None else None,
        "recentCloses": technical["recent_closes"] if technical else [],
        "recentVolumes": technical["recent_volumes"] if technical else [],
        "recentDates": technical["recent_dates"] if technical else [],
    }
    chart_json = json.dumps(chart_payload, ensure_ascii=False)
    news_lines = "\n".join([f"- {h}" for h in headlines]) if headlines else "- 暫無最新新聞"

    parts = [
        f"## {code} {name}",
        "",
        "### 1. 圖表顯示",
        f'<div class="stock-chart-block" data-stock=\'{chart_json}\'></div>',
        "",
        "### 2. 小G建議",
        advice,
        "",
        "### 3. 近期新聞",
        news_lines,
        "",
    ]
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="一鍵自動填台股自選股模板")
    parser.add_argument("--codes", default="自選股清單.txt")
    parser.add_argument("--template", default="台股自選股_AI報告模板.md")
    parser.add_argument("--model", default="gemini-2.5-flash")
    parser.add_argument("--skip-ai", action="store_true")
    parser.add_argument("--copy", action="store_true")
    args = parser.parse_args()

    codes_path = Path(args.codes)
    template_path = Path(args.template)
    if not codes_path.exists():
        raise FileNotFoundError(f"找不到股票清單：{codes_path}")

    codes = read_stock_codes(codes_path)
    if not codes:
        raise RuntimeError("股票清單是空的，請至少放一檔代號。")

    print(f"讀取股票清單：{codes}")
    quote_map = get_quote_map(codes)

    stock_pairs = []
    stock_info_map = {}
    stock_blocks = []

    for code in codes:
        quote = quote_map.get(code)
        if not quote:
            stock_blocks.append(f"## {code}\n\n查無即時報價，請確認代號是否正確。\n")
            continue

        suffix = ".TW" if quote.get("ex") == "tse" else ".TWO"
        technical = get_technical_stats(f"{code}{suffix}")
        headlines = get_news_headlines(f"{code} {quote.get('n', '')} 台股", limit=3)

        stock_name = quote.get("n", "N/A")
        market = "上市" if quote.get("ex") == "tse" else "上櫃"
        last = to_float(quote.get("z") or quote.get("y"))
        prev = to_float(quote.get("y"))
        high = to_float(quote.get("h"))
        low = to_float(quote.get("l"))
        open_price = to_float(quote.get("o"))
        volume = to_float(quote.get("v"))
        diff = (last - prev) if (last is not None and prev is not None) else None
        pct = ((diff / prev) * 100) if (diff is not None and prev) else None

        close_text = "N/A"
        if last is not None and diff is not None and pct is not None:
            close_text = f"{last:.2f}（{format_signed(diff, 2)}，{format_signed(pct, 2)}%）"

        if technical:
            ma_text = f"5MA {technical['ma5']:.2f} / 20MA {technical['ma20']:.2f} / 60MA {technical['ma60']:.2f}"
            range_text = f"20日高低 {technical['high20']:.2f} / {technical['low20']:.2f}"
            vol_ratio_text = f"{technical['vol_ratio']:.2f}" if technical["vol_ratio"] is not None else "N/A"
        else:
            ma_text = "N/A"
            range_text = "N/A"
            vol_ratio_text = "N/A"

        ohl_text = f"{open_price if open_price is not None else 'N/A'} / {high if high is not None else 'N/A'} / {low if low is not None else 'N/A'}"
        volume_text = f"{int(volume):,}" if volume is not None else "N/A"

        stock_info = {
            "code": code,
            "name": stock_name,
            "market": market,
            "close_text": close_text,
            "ohl_text": ohl_text,
            "volume_text": volume_text,
            "ma_text": ma_text,
            "range_text": range_text,
            "vol_ratio_text": vol_ratio_text,
        }
        stock_info_map[code] = stock_info
        stock_pairs.append((code, stock_name))

        print(f"  [{code} {stock_name}] 取得資料，呼叫 Gemini 小G建議…")
        advice = "已略過 AI 分析。" if args.skip_ai else generate_stock_advice(stock_info, args.model)
        block = build_stock_block(code, quote, technical, headlines, advice)
        stock_blocks.append(block)

    date_text = dt.datetime.now().strftime("%Y-%m-%d")
    now_text = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    code_list_lines = "\n".join([f"- {code} {name}" for code, name in stock_pairs]) if stock_pairs else "- N/A"

    print("呼叫 Gemini：大盤走勢分析…")
    market_overview = "已略過 AI 大盤分析。" if args.skip_ai else generate_market_overview(date_text, stock_pairs, stock_info_map, args.model)

    print("呼叫 Gemini：自選股綜合評價…")
    overall_eval = "已略過 AI 綜合評價。" if args.skip_ai else generate_overall_evaluation(date_text, stock_pairs, stock_info_map, args.model)

    all_stock_blocks = "\n---\n\n".join(stock_blocks).strip()

    content = (
        "# 台股自選股追蹤報告\n\n"
        "---\n\n"
        "# 本週大盤走勢分析\n\n"
        f"{market_overview}\n\n"
        "---\n\n"
        "# 自選股清單\n\n"
        f"{code_list_lines}\n\n"
        "---\n\n"
        "# 個股分析\n\n"
        f"{all_stock_blocks}\n\n"
        "---\n\n"
        "# 自選股綜合評價\n\n"
        f"{overall_eval}\n\n"
        "---\n\n"
        "*資料來源：台灣證券交易所、雅虎財經、Google 新聞、Google Gemini AI*\n"
        "*本報告僅供參考，不構成任何投資建議。*\n"
    )

    template_path.write_text(content, encoding="utf-8")
    print(f"已更新報告：{template_path}")

    if args.copy:
        copy_path = template_path.parent / f"台股自選股_AI報告_{dt.datetime.now().strftime('%Y%m%d')}.md"
        copy_path.write_text(content, encoding="utf-8")
        print(f"已輸出副本：{copy_path}")


if __name__ == "__main__":
    main()