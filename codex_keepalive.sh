#!/bin/bash

# Inherit HTTP proxies from the shell or configure them here
# export http_proxy="http://127.0.0.1:7897"
# export https_proxy="http://127.0.0.1:7897"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$HOME/.codex_keepalive.log"

echo "=============================================" >> "$LOG_FILE"
echo "开始执行 Codex 智能唤醒与状态同步: $(date)" >> "$LOG_FILE"

# Run the python keepalive script
python3 "$SCRIPT_DIR/codex_keepalive.py" >> "$LOG_FILE" 2>&1

echo "唤醒任务结束于: $(date)" >> "$LOG_FILE"
echo "=============================================" >> "$LOG_FILE"
