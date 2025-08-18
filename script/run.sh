#!/bin/bash
# Запуск бота в фоне
echo "🚀 Starting bot..."
nohup .venv/bin/python -m app.bot > bot.log 2>&1 & echo $! > bot.pid
echo "✅ Bot started with PID $(cat bot.pid)"