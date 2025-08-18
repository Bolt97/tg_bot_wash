#!/bin/bash
# Остановка бота
if [ -f bot.pid ]; then
    PID=$(cat bot.pid)
    if ps -p $PID > /dev/null; then
        kill $PID
        echo "🛑 Bot (PID $PID) stopped"
    else
        echo "⚠️  No running process found for PID $PID"
    fi
    rm -f bot.pid
else
    echo "⚠️  bot.pid not found (maybe bot is not running?)"
fi