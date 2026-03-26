import os
import json
import logging
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("ClaudeAnalyzer")

try:
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
except Exception as e:
    logger.error("Failed to initialize Anthropic client. Please check ANTHROPIC_API_KEY.")
    client = None

def load_prompt_template():
    try:
        with open("prompt.txt", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error loading prompt template: {e}")
        return ""

def analyze_market_custom(market_question, yes_price, no_price, 
                          current_btc_price, recent_change, volatility, 
                          news_summary, oracle_data, base_rate):
    """
    Sends contextual data to Claude to get fair probability.
    Returns parsed JSON dictionary or None.
    """
    if not client:
        return None

    template = load_prompt_template()
    if not template:
        return None

    prompt = template.format(
        MARKET_QUESTION=market_question,
        YES_PRICE=yes_price,
        NO_PRICE=no_price,
        CURRENT_BTC_PRICE=current_btc_price,
        RECENT_CHANGE=recent_change,
        VOLATILITY=volatility,
        NEWS_SUMMARY=news_summary,
        ORACLE_DATA=oracle_data,
        BASE_RATE=base_rate
    )

    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            temperature=0.2,
            system="You are a strict JSON outputting AI. Always output valid JSON matching the exact required format. Do not use markdown blocks, output raw JSON.",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        
        text_resp = response.content[0].text.strip()
        
        # Strip markdown blocks if Claude includes them despite system prompt
        if text_resp.startswith("```json"):
            text_resp = text_resp.split("```json", 1)[1]
        elif text_resp.startswith("```"):
            text_resp = text_resp.split("```", 1)[1]
            
        if text_resp.endswith("```"):
            text_resp = text_resp.rsplit("```", 1)[0]
            
        text_resp = text_resp.strip()
        
        data = json.loads(text_resp)
        return data
        
    except json.JSONDecodeError as je:
        logger.error(f"Failed to parse Claude JSON response: {je}\nResponse was: {text_resp}")
        return None
    except Exception as e:
        logger.error(f"Claude API Error: {e}")
        return None
