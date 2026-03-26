import requests
import logging

logger = logging.getLogger("Scanner")

def get_current_btc_stats():
    """
    Fetch current BTC price and 24h stats from Binance public API
    """
    try:
        resp = requests.get("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT")
        resp.raise_for_status()
        data = resp.json()
        return {
            "current_price": float(data['lastPrice']),
            "recent_change_pct": float(data['priceChangePercent']),
            "volatility": float(data['priceChangePercent']), # Approximated as 24h change for now
            "oracle_data": f"Binance 24h High: {data['highPrice']}, Low: {data['lowPrice']}",
            "base_rate": "Historical win rate around 50% for standard thresholds",
            "news_summary": "N/A"
        }
    except Exception as e:
        logger.error(f"Error fetching BTC stats: {e}")
        return {
            "current_price": 0.0,
            "recent_change_pct": 0.0,
            "volatility": 0.0,
            "oracle_data": "N/A",
            "base_rate": "N/A",
            "news_summary": "N/A"
        }

def fetch_btc_markets():
    """
    Fetches active BTC related markets from Polymarket's Gamma API.
    """
    url = "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=100"
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        events = resp.json()
        
        btc_markets = []
        for event in events:
            title = event.get('title', '').lower()
            if 'bitcoin' in title or 'btc' in title:
                for market in event.get('markets', []):
                    if market.get('active') and not market.get('closed') and market.get('acceptingOrders'):
                        # get current prices
                        tokens = market.get('tokens', [])
                        if len(tokens) == 2:
                            # Usually outcomePrices is [Yes, No]
                            prices = market.get('outcomePrices', ['0.5', '0.5'])
                            yes_price = float(prices[0])
                            no_price = float(prices[1])
                            
                            liquidity = float(market.get('liquidity', 0))
                            
                            if liquidity > 500: # Filter low liquidity
                                
                                # Find Yes Token ID
                                yes_token_id = ""
                                no_token_id = ""
                                if tokens[0].get('outcome', '').lower() == 'yes':
                                    yes_token_id = tokens[0].get('token_id')
                                    no_token_id = tokens[1].get('token_id')
                                elif len(tokens) > 1 and tokens[1].get('outcome', '').lower() == 'yes':
                                    yes_token_id = tokens[1].get('token_id')
                                    no_token_id = tokens[0].get('token_id')
                                
                                btc_markets.append({
                                    'event_title': event.get('title'),
                                    'market_id': market.get('id'),
                                    'condition_id': market.get('conditionId'),
                                    'question': market.get('question'),
                                    'yes_token_id': yes_token_id,
                                    'no_token_id': no_token_id,
                                    'yes_price': yes_price,
                                    'no_price': no_price,
                                    'liquidity': liquidity,
                                    'volume': float(market.get('volumeNum', 0))
                                })
        return btc_markets
    except Exception as e:
        logger.error(f"Error fetching Polymarket events: {e}")
        return []

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    stats = get_current_btc_stats()
    print("BTC Stats:", stats)
    markets = fetch_btc_markets()
    print(f"Found {len(markets)} active high-liq BTC markets.")
    for m in markets[:5]:
        print(f" - {m['question'][:60]}... (Y:{m['yes_price']}, N:{m['no_price']}, Liq:{m['liquidity']})")
