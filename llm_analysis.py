"""LLM stub — returns empty string so agent.py falls back to raw analysis."""
 
from __future__ import annotations
 
 
def build_llm_full_analysis(ticker: str, raw_analysis: str) -> str:
    return raw_analysis
 
 
def build_llm_news_analysis(ticker: str, raw_analysis: str) -> str:
    return raw_analysis
 
 
def build_llm_risks_analysis(ticker: str, raw_analysis: str) -> str:
    return raw_analysis
 
 
def build_llm_idea(ticker: str, raw_analysis: str) -> str:
    return raw_analysis
 
 
def build_llm_today_ideas(tickers_data: list[dict]) -> str:
    lines = ["📈 Идеи дня\n"]
    for item in tickers_data:
        ticker = item.get("ticker", "")
        raw = item.get("raw_analysis", "")[:500]
        lines.append(f"*{ticker}*\n{raw}\n")
    return "\n".join(lines)
