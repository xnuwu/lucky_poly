import os
import sys
import base64
import getpass
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet

def set_env_value(filepath, key, value):
    if not os.path.exists(filepath):
        with open(filepath, "w") as f:
            f.write("")
            
    with open(filepath, "r") as f:
        lines = f.readlines()
        
    found = False
    with open(filepath, "w") as f:
        for line in lines:
            if line.startswith(f"{key}="):
                f.write(f"{key}={value}\n")
                found = True
            elif line.startswith("POLYGON_PRIVATE_KEY="):
                f.write(f"# POLYGON_PRIVATE_KEY=removed_for_security\n")
            else:
                f.write(line)
        if not found:
            f.write(f"{key}={value}\n")

def encrypt():
    # 查找私钥
    poly_key = None
    if os.path.exists("en_key.txt"):
        with open("en_key.txt", "r") as f:
            poly_key = f.read().strip()
    
    # 查找 Claude API Key
    claude_key = None
    if os.path.exists("claude_api_key.txt"):
        with open("claude_api_key.txt", "r") as f:
            claude_key = f.read().strip()
        
    if not poly_key and not claude_key:
        print("❌ 错误: 未找到 en_key.txt 或 claude_api_key.txt！")
        sys.exit(1)

    print("🔒 准备为您加密存储敏感密钥。")
    password = getpass.getpass("请输入你想设置的加密密码 (输入时屏幕不显示): ")
    password_confirm = getpass.getpass("请再次输入确认密码: ")
    
    if password != password_confirm:
        print("❌ 错误: 两次输入的密码不一致！")
        sys.exit(1)
        
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    f_crypt = Fernet(key)
    
    if poly_key:
        encrypted_poly = f_crypt.encrypt(poly_key.encode())
        set_env_value(".env", "ENCRYPTED_POLYGON_PRIVATE_KEY", encrypted_poly.decode())
        # 彻底擦除文件痕迹
        with open("en_key.txt", "w") as f:
            f.write("deleted_safely")
        os.remove("en_key.txt")
        print("✅ Polygon 私钥已加密。")

    if claude_key:
        encrypted_claude = f_crypt.encrypt(claude_key.encode())
        set_env_value(".env", "ENCRYPTED_ANTHROPIC_API_KEY", encrypted_claude.decode())
        with open("claude_api_key.txt", "w") as f:
            f.write("deleted_safely")
        os.remove("claude_api_key.txt")
        print("✅ Anthropic API Key 已加密。")
    
    set_env_value(".env", "CRYPTO_SALT", base64.b64encode(salt).decode())
    
    print("✅ 所有敏感密钥已安全保存至 .env，原始文本文件已销毁。")

if __name__ == "__main__":
    encrypt()
