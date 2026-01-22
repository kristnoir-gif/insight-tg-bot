#!/bin/bash
cd /Users/kristina/kris_/bot_tg
nohup python3 main.py > bot.log 2>&1 &
echo "Бот запущен (PID: $!)"
sleep 2
tail -f bot.log
