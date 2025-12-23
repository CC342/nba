#!/bin/bash

# 固定脚本目录
BASE_DIR="/home/nba"
WX_SCRIPT="$BASE_DIR/wx.py"
TG_SCRIPT="$BASE_DIR/nbabot.py"
OT_SCRIPT="$BASE_DIR/other.py"
OT2_SCRIPT="$BASE_DIR/other2.py"

# 获取单个 PID（取第一个）
get_pid() {
    local script=$1
    pid=$(pgrep -f "$(basename "$script")" | head -n1)
    echo "$pid"
}

# 显示状态
show_status() {
    wx_pid=$(get_pid "$WX_SCRIPT")
    tg_pid=$(get_pid "$TG_SCRIPT")
    ot_pid=$(get_pid "$OT_SCRIPT")
    ot2_pid=$(get_pid "$OT2_SCRIPT")
    echo -e "======================================"
    echo -e "当前脚本状态："
    if [ -n "$wx_pid" ]; then
        echo -e "wx.py        : \e[32m已启动 (PID: $wx_pid)\e[0m"
    else
        echo -e "wx.py        : \e[31m未启动\e[0m"
    fi
    if [ -n "$tg_pid" ]; then
        echo -e "nbabot.py    : \e[32m已启动 (PID: $tg_pid)\e[0m"
    else
        echo -e "nbabot.py    : \e[31m未启动\e[0m"
    fi
    if [ -n "$ot_pid" ]; then
        echo -e "other.py     : \e[32m已启动 (PID: $ot_pid)\e[0m"
    else
        echo -e "other.py     : \e[31m未启动\e[0m"
    fi    
    if [ -n "$ot2_pid" ]; then
        echo -e "other2.py    : \e[32m已启动 (PID: $ot2_pid)\e[0m"
    else
        echo -e "other2.py    : \e[31m未启动\e[0m"
    fi
    echo -e "======================================"
}

# 启动脚本
start_script() {
    local script=$1
    pid=$(get_pid "$script")
    if [ -n "$pid" ]; then
        echo -e "$script 已经在运行 (PID: $pid)"
    else
        nohup python3 "$script" >"$BASE_DIR/$(basename "$script").log" 2>&1 &
        sleep 1
        pid=$(get_pid "$script")
        if [ -n "$pid" ]; then
            echo -e "$script 启动成功 (PID: $pid)"
        else
            echo -e "$script 启动失败，查看日志: $BASE_DIR/$(basename "$script").log"
        fi
    fi
}

# 停止脚本
stop_script() {
    local script=$1
    pid=$(get_pid "$script")
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null
        sleep 1
        pid=$(get_pid "$script")
        if [ -z "$pid" ]; then
            echo -e "$script \e[32m已停止\e[0m"
        else
            echo -e "$script \e[31m停止失败\e[0m"
        fi
    # 注意：这里去掉了 "未运行" 的提示，避免自动切换时刷屏，
    # 如果你想保留那个提示，可以把 else echo... 加回来
    fi
}

# 主循环
while true; do
    show_status
    echo "请选择操作："
    echo "1) 启动 微信命令"
    echo "2) 停止 微信命令"
    echo "3) 启动 TG命令"
    echo "4) 停止 TG命令"
    echo "5) 启动 其他直连 (会自动关闭 代理)"
    echo "6) 停止 其他直连"
    echo "7) 启动 其他代理 (会自动关闭 直连)"
    echo "8) 停止 其他代理"
    echo "9) 退出"
    read -p "输入选项 (1-9): " choice
    case $choice in
        1) start_script "$WX_SCRIPT" ;;
        2) stop_script "$WX_SCRIPT" ;;
        3) start_script "$TG_SCRIPT" ;;
        4) stop_script "$TG_SCRIPT" ;;
        5) 
            # 启动 other.py 前，先停止 other2.py
            echo ">>> 正在检测冲突进程..."
            stop_script "$OT2_SCRIPT"
            start_script "$OT_SCRIPT" 
            ;;
        6) stop_script "$OT_SCRIPT" ;;
        7) 
            # 启动 other2.py 前，先停止 other.py
            echo ">>> 正在检测冲突进程..."
            stop_script "$OT_SCRIPT"
            start_script "$OT2_SCRIPT" 
            ;;
        8) stop_script "$OT2_SCRIPT" ;;
        9) echo "退出管理脚本"; exit 0 ;;
        *) echo "无效选项，请输入 1-9" ;;
    esac
    echo
done
