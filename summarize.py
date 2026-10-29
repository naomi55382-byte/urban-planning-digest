"""用 Claude 把當日新增的公告與新聞整理成「每日重點」。

需要環境變數 ANTHROPIC_API_KEY 與套件 anthropic（pip install anthropic）；
缺少任一項時 collect.py 會略過這一步，網頁照常產生。
"""
import json

import anthropic

MODEL = "claude-opus-5-5"

SYSTEM = """你是協助都市計畫從業人員掌握每日動態的助理。使用者每天只有約 10 分鐘，
請從當日蒐集到的公告與新聞標題中，整理出最值得注意的重點。

原則：
- 只根據提供的標題與欄位內容整理，不要推測標題沒有寫到的細節（金額、面積、日期等）。
- 優先順序：公開展覽／說明會／聽證等有期限、可參與的事項 > 計畫核定、發布實施 > 政策方向與重大新聞 > 一般活動。
- 同一案件的多則公告或新聞合併成一點。
- 使用臺灣常用的繁體中文用語，語氣精簡、專業。
- refs 填入引用項目的編號（方括號內的數字）。"""

SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {"type": "string", "description": "今日整體概況，2～3 句"},
        "highlights": {
            "type": "array",
            "description": "今日最重要的 5～8 個重點，依重要性排序",
            "items": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "title": {"type": "string", "description": "15 字以內的重點標題"},
                    "detail": {"type": "string", "description": "1～2 句說明為什麼值得注意"},
                    "refs": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["city", "title", "detail", "refs"],
                "additionalProperties": False,
            },
        },
        "deadlines": {
            "type": "array",
            "description": "標題中明確提到的公開展覽、說明會、聽證、受理申請等期限或日期；沒有就留空",
            "items": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "what": {"type": "string"},
                    "when": {"type": "string", "description": "照標題原文寫出日期或期間"},
                    "refs": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["city", "what", "when", "refs"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overview", "highlights", "deadlines"],
    "additionalProperties": False,
}


def summarize(items, today):
    """items 為當日新增項目；回傳整理結果 dict，refs 已換成 item 的連結。"""
    lines = [
        f'[{i}] {it["city"]}｜{it["kind"]}｜{"、".join(it["topics"])}｜{it["source"]}｜{it["date"] or "日期不明"}｜{it["title"]}'
        for i, it in enumerate(items, 1)
    ]
    prompt = f"今天是 {today}。以下是今日新增的 {len(items)} 則項目：\n\n" + "\n".join(lines)

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"模型拒絕回應：{response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("輸出超過長度上限")

    text = next(b.text for b in response.content if b.type == "text")
    result = json.loads(text)

    def links(refs):
        return [{"title": items[r - 1]["title"], "link": items[r - 1]["link"]}
                for r in refs if 1 <= r <= len(items)]

    for h in result["highlights"] + result["deadlines"]:
        h["refs"] = links(h["refs"])
    result.update(date=today, count=len(items), model=response.model)
    print(f"[摘要] 輸入 {response.usage.input_tokens} tokens，輸出 {response.usage.output_tokens} tokens")
    return result
