#!/bin/bash
# Проверка статуса бота
if [ -f bot.pid ]; then
    PID=$(cat bot.pid)
    if ps -p $PID > /dev/null; then
        echo "✅ Bot is running (PID $PID)"
    else
        echo "⚠️  bot.pid exists but process not found"
    fi
else
    echo "⚠️  Bot not running"
fi