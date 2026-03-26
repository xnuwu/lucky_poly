#!/bin/bash

echo "🚀 开始部署 Polymarket BTC 交易机器人..."

# 1. 检查 Python3
if ! command -v python3 &> /dev/null
then
    echo "❌ 错误: 未找到 Python3。如果是在 Ubuntu 上，请先运行: sudo apt install python3 python3-venv"
    exit 1
fi

# 2. 建立虚拟环境
echo "📦 正在创建 Python 虚拟环境 (venv)..."
python3 -m venv venv
source venv/bin/activate

# 3. 安装依赖
echo "📥 正在安装 requirements.txt 依赖..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. 检查环境变量
if [ ! -f .env ]; then
    echo "⚠️ 警告: 未找到 .env 文件！请确保您将本地的 .env 也复制到了服务器。"
    echo "   如果是在测试，也可以继续，机器人会自动进入无害无损的空跑（Dry-Run）模式记录日志。"
fi

if grep -q "ENCRYPTED_POLYGON_PRIVATE_KEY=" .env 2>/dev/null; then
    echo "🔒 检测到强加密保护机制！需要启动密码才能解锁私钥进行交易。"
    read -s -p "请输入您的密码: " BOT_PASSWORD
    echo ""
    export BOT_PASSWORD
fi

# 5. PM2 部署
echo "⚙️ 正在使用 PM2 启动主循环..."
# 清除旧可能存在的同名进程，避免冲突
pm2 delete poly-btc-bot 2>/dev/null || true

# 关键: 使用 venv 内置的 python 来保证依赖读取正确
pm2 start main_loop.py --name "poly-btc-bot" --interpreter=./venv/bin/python

# 6. 保存 PM2
echo "💾 保存 PM2 进程状态以便开机自启..."
pm2 save

echo ""
echo "✅ 部署脚本执行完毕！"
echo "👉 您现在可以在服务器上运行以下命令监控日志："
echo "   pm2 logs poly-btc-bot"
