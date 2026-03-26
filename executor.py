import os
import logging
from py_clob_client.client import ClobClient, ClobAuth
from py_clob_client.clob_types import OrderArgs, OrderType
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("Executor")

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137 # Polygon mainnet

def get_client():
    private_key = os.environ.get("POLYGON_PRIVATE_KEY")

    if not private_key or "your_" in private_key:
        logger.warning("POLYGON_PRIVATE_KEY is not configured in .env. Dry run mode active.")
        return None

    try:
        client = ClobClient(host=HOST, key=private_key, chain_id=CHAIN_ID)
        
        # Automatically derive credentials via wallet signature
        logger.info("Automatically deriving Polymarket credentials from wallet signature...")
        creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)
            
        return client
    except Exception as e:
        logger.error(f"Failed to initialize CLOB client: {e}")
        return None

def calculate_kelly_bet_size(fair_prob, market_prob, bankroll):
    """
    bankroll: total available capital (USDC)
    fair_prob: our edge probability
    market_prob: current market price
    """
    b = (1.0 - market_prob) / market_prob
    p = fair_prob
    q = 1.0 - p
    
    if b <= 0: return 0.0
    f = (b * p - q) / b
    
    if f <= 0:
        return 0.0
        
    kelly_fraction_modifier = float(os.environ.get("KELLY_FRACTION", "1.0"))
    f_modified = f * kelly_fraction_modifier
    
    max_risk = float(os.environ.get("MAX_RISK_PER_TRADE", "0.05"))
    f_modified = min(f_modified, max_risk)
    
    bet_size = bankroll * f_modified
    
    if os.environ.get("PENNY_BET_MODE", "false").lower() == "true":
        return 1.0
        
    return bet_size

def execute_trade(market, analysis_result):
    """
    Takes market data and analysis, fetches real L2 depth, places FOK order.
    """
    client = get_client()
    if not client:
         logger.info("Dry run: CLOB client not available. Skipping execution.")
         return False

    bankroll = float(os.environ.get("TOTAL_CAPITAL_USDC", "50.0"))
    fair_prob = analysis_result.get("fair_yes_probability", 0)
    
    if analysis_result.get("recommended_action") == "BUY_YES":
        market_prob = market["yes_price"]
        token_id = market["yes_token_id"]
        side = "BUY"
    elif analysis_result.get("recommended_action") == "BUY_NO":
        market_prob = market["no_price"]
        token_id = market["no_token_id"]
        side = "BUY"
    else:
        return False

    # 1. Fetch real L2 orderbook for exact spread matching
    try:
        ob = client.get_order_book(token_id)
        asks = ob.asks if hasattr(ob, 'asks') else ob.get('asks', [])
        if not asks:
            logger.info(f"Orderbook empty on ASK side for token {token_id}. Cannot execute.")
            return False
            
        parsed_asks = []
        for a in asks:
            price = float(a.price) if hasattr(a, 'price') else float(a['price'])
            size = float(a.size) if hasattr(a, 'size') else float(a['size'])
            parsed_asks.append({"price": price, "size": size})
            
        parsed_asks.sort(key=lambda x: x["price"])
        best_ask_price = parsed_asks[0]["price"]
        
        # Verify edge exists against real L2 ask price
        min_edge = float(os.environ.get("MIN_EDGE_PERCENT", "8.0"))
        current_edge = (fair_prob - best_ask_price) * 100
        
        if current_edge < min_edge:
            logger.info(f"Edge lost at real L2 ask {best_ask_price:.3f} (Edge: {current_edge:.1f}% vs required {min_edge}%). Aborting.")
            return False
            
        market_prob = best_ask_price
    except Exception as e:
        logger.error(f"Failed to fetch orderbook for {token_id}, relying on Gamma API price: {e}")

    bet_amount_usdc = calculate_kelly_bet_size(fair_prob, market_prob, bankroll)
    if bet_amount_usdc < 0.5:
        logger.info(f"Bet size too small ({bet_amount_usdc:.2f} USDC)")
        return False
        
    num_shares = bet_amount_usdc / market_prob
    
    logger.info(f"Executing FOK trade: {side} {num_shares:.2f} shares @ {market_prob} USDC for token {token_id}")
    
    try:
        order_args = OrderArgs(
            price=market_prob,
            size=num_shares,
            side=side,
            token_id=token_id
        )
        signed_order = client.create_order(order_args)
        resp = client.post_order(signed_order, OrderType.FOK)
        logger.info(f"Order posted: {resp}")
        return True
    except Exception as e:
        logger.error(f"Failed to place order: {e}")
        return False
