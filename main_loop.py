import os
import sys
import time
import requests
import logging
import traceback
from dotenv import load_dotenv

LAST_UPDATE_ID = None
IS_PAUSED = False
MARKET_STATE_CACHE = {}

from scanner import fetch_btc_markets, get_current_btc_stats
from claude_analyzer import analyze_market_custom
from executor import execute_trade

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("MainBot")

load_dotenv()

def send_telegram_message(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id or token == "your_tg_bot_token_here":
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": msg})
    except Exception as e:
        logger.error(f"TG notification failed: {e}")

def check_telegram_commands():
    global LAST_UPDATE_ID, IS_PAUSED
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id or "your_" in token:
        return

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"timeout": 3}
    if LAST_UPDATE_ID is not None:
        params["offset"] = LAST_UPDATE_ID + 1

    try:
        resp = requests.get(url, params=params, timeout=5)
        data = resp.json()
        if data.get("ok"):
            for update in data.get("result", []):
                LAST_UPDATE_ID = update["update_id"]
                msg = update.get("message", {})
                
                if str(msg.get("chat", {}).get("id")) == str(chat_id):
                    text = msg.get("text", "").strip().lower()
                    if text in ["/stop", "stop"]:
                        if not IS_PAUSED:
                            IS_PAUSED = True
                            send_telegram_message("🛑 收到暂停命令。机器人已暂停监控，输入 /start 可恢复。")
                            logger.info("Bot paused via Telegram.")
                        else:
                            send_telegram_message("⚠️ 机器人当前已经是暂停状态。")
                    elif text in ["/start", "start"]:
                        if IS_PAUSED:
                            IS_PAUSED = False
                            send_telegram_message("▶️ 收到启动命令。机器人恢复监控！")
                            logger.info("Bot resumed via Telegram.")
                        else:
                            send_telegram_message("⚠️ 机器人当前已经在运行中。")
                    elif text in ["/status", "status"]:
                        status_str = "⏸️ 暂停中" if IS_PAUSED else "▶️ 运行中"
                        send_telegram_message(f"状态: {status_str}\n（正在随时听候指令）")
    except Exception as e:
        logger.error(f"Error checking Telegram commands: {e}")

def run_cycle():
    logger.info("Starting new scan cycle...")
    
    current_balance = get_usdc_balance()
    private_key = os.environ.get("POLYGON_PRIVATE_KEY")
    is_dry_run = (not private_key or "your_" in private_key)
    if not is_dry_run and current_balance < 0.5:
        logger.warning(f"余额告警: ({current_balance:.2f} USDC) 不足以交易。暂停 Claude API 分析请求以节省您的 API 成本！")
        return
        
    stats = get_current_btc_stats()
    markets = fetch_btc_markets()
    
    if not markets:
        logger.info("No active BTC markets found.")
        return

    logger.info(f"Scanning {len(markets)} BTC markets.")
    
    min_edge_percent = float(os.environ.get("MIN_EDGE_PERCENT", "8.0"))
    min_confidence = float(os.environ.get("MIN_CONFIDENCE", "0.65"))

    for m in markets:
        try:
            if not m.get('yes_price') or not m.get('no_price'):
                continue
                
            market_id = m.get('condition_id', m.get('question'))
            current_yes = float(m['yes_price'])
            
            # State Caching Logic: skip Claude API if stable
            last_state = MARKET_STATE_CACHE.get(market_id)
            if last_state:
                time_diff = time.time() - last_state['time']
                price_diff = abs(current_yes - last_state['yes_price'])
                if time_diff < 600 and price_diff < 0.02:
                    continue
                
            logger.info(f"Analyzing (API Call): {m['question'][:60]}... (Y:{m['yes_price']} N:{m['no_price']})")
            
            result = analyze_market_custom(
                market_question=m['question'],
                yes_price=m['yes_price'],
                no_price=m['no_price'],
                current_btc_price=stats['current_price'],
                recent_change=stats['recent_change_pct'],
                volatility=stats['volatility'],
                news_summary=stats['news_summary'],
                oracle_data=stats['oracle_data'],
                base_rate=stats['base_rate']
            )

            if not result:
                continue
                
            MARKET_STATE_CACHE[market_id] = {
                'time': time.time(),
                'yes_price': current_yes
            }

            edge = result.get("edge_percent", 0)
            confidence = result.get("confidence_score", 0)
            action = result.get("recommended_action", "NO_TRADE")
            
            logger.info(f"Claude Output -> Action: {action}, Edge: {edge}%, Conf: {confidence}")

            if action in ["BUY_YES", "BUY_NO"] and edge >= min_edge_percent and confidence >= min_confidence:
                msg = (f"🚨 Edge Detected!\nMarket: {m['question']}\nAction: {action}\nEdge: {edge}%\n"
                       f"Conf: {confidence}\nReason: {result.get('reasoning_summary')}")
                logger.info(msg)
                send_telegram_message(msg)

                success = execute_trade(m, result)
                if success:
                    send_telegram_message(f"✅ Trade Executed Successfully for [ {m['question']} ]")
                else:
                    send_telegram_message(f"❌ Trade Execution Failed or Dry-run for [ {m['question']} ]")
                    
        except Exception as e:
            err = f"Error processing market {m.get('question', 'Unknown')}: {e}\n{traceback.format_exc()}"
            logger.error(err)

def load_and_decrypt_key():
    encrypted_poly = os.environ.get("ENCRYPTED_POLYGON_PRIVATE_KEY")
    encrypted_claude = os.environ.get("ENCRYPTED_ANTHROPIC_API_KEY")
    salt_b64 = os.environ.get("CRYPTO_SALT")
    
    if (encrypted_poly or encrypted_claude) and salt_b64:
        password = os.environ.get("BOT_PASSWORD")
        if not password:
            import getpass
            password = getpass.getpass("🔑 [Security] 检测到加密密钥，请输入解密密码: ")
            
        import base64
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.fernet import Fernet
        
        try:
            salt = base64.b64decode(salt_b64)
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=480000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            f = Fernet(key)
            
            if encrypted_poly:
                decrypted_poly = f.decrypt(encrypted_poly.encode()).decode()
                os.environ["POLYGON_PRIVATE_KEY"] = decrypted_poly
                logger.info("🔑 Polygon 私钥解密成功")
                
            if encrypted_claude:
                decrypted_claude = f.decrypt(encrypted_claude.encode()).decode()
                os.environ["ANTHROPIC_API_KEY"] = decrypted_claude
                logger.info("🔑 Anthropic API Key 解密成功")
                
        except Exception as e:
            err_msg = str(e) if str(e) else "密码错误 (Invalid Token)"
            logger.error(f"❌ 解密失败: {err_msg}")
            import sys
            sys.exit(1)

def get_usdc_balance():
    private_key = os.environ.get("POLYGON_PRIVATE_KEY")
    if not private_key or "your_" in private_key:
        return 0.0
    try:
        from web3 import Web3
        rpc_url = "https://polygon-rpc.com"
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        account = w3.eth.account.from_key(private_key)
        usdc_address = w3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
        usdc_abi = [{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]
        usdc_contract = w3.eth.contract(address=usdc_address, abi=usdc_abi)
        balance_wei = usdc_contract.functions.balanceOf(account.address).call()
        return balance_wei / 1e6
    except Exception as e:
        logger.error(f"Fetch USDC balance failed: {e}")
        return 0.0

def check_trading_environment():
    load_and_decrypt_key()
    
    private_key = os.environ.get("POLYGON_PRIVATE_KEY")
    if not private_key or "your_" in private_key:
        logger.info("Starting in DRY RUN mode. No trading will occur.")
        send_telegram_message("🚀 启动空跑(Dry-Run)模式并开始监控。配置私钥后方可实盘交易！")
        return False
        
    try:
        balance_usdc = get_usdc_balance()
        from executor import get_client
        client = get_client() # Validate derivation
        if client:
            msg = f"✅ 成功连接 Polymarket 并派生 API！\n💳 钱包 USDC 余额: {balance_usdc:.2f}"
            logger.info(msg)
            send_telegram_message(msg)
            return True
        else:
            raise Exception("CLOB client formulation failed.")
    except Exception as e:
        logger.error(f"Authentication test failed: {e}")
        send_telegram_message(f"❌ 钱包连接或认证失败，请检查私钥: {e}")
        return False

def main():
    logger.info("Polymarket BTC Trading Bot Started.")
    check_trading_environment()
    
    poll_interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "10"))
    
    cycle_count = 0
    while True:
        try:
            check_telegram_commands()
            if not IS_PAUSED:
                cycle_count += 1
                logger.info(f"--- Cycle {cycle_count} ---")
                run_cycle()
            else:
                logger.info("Bot is paused. Waiting for /start command...")
        except KeyboardInterrupt:
            logger.info("Bot shutting down manually.")
            break
        except Exception as e:
            err_msg = f"Fatal error in main loop: {e}"
            logger.error(err_msg)
            send_telegram_message(f"⚠️ {err_msg}")
            
        logger.info(f"Sleeping for {poll_interval} seconds...")
        time.sleep(poll_interval)

if __name__ == "__main__":
    main()
