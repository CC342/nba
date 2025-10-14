#!/bin/bash

WX_SCRIPT="/home/nba/wx.py"
NBA_SCRIPT="/home/nba/nbabot.py"

# 检查脚本状态
check_status() {
    WX_PID=$(pgrep -f "$WX_SCRIPT")
    NBA_PID=$(pgrep -f "$NBA_SCRIPT")

    echo "======================================"
    echo "当前脚本状态："
    if [ -n "$WX_PID" ]; then
        echo -e "wx.py        : \033[1;32m已启动 (PID: $WX_PID)\033[0m"
    else
        echo -e "wx.py        : \033[1;31m未启动\033[0m"
    fi

    if [ -n "$NBA_PID" ]; then
        echo -e "nbabot.py    : \033[1;32m已启动 (PID: $NBA_PID)\033[0m"
    else
        echo -e "nbabot.py    : \033[1;31m未启动\033[0m"
    fi
    echo "======================================"
}

# 启动单个脚本
start_script() {
    local script_name=$1
    local script_path=$2
    local pid_var=$3

    if [ -z "$(eval echo \$$pid_var)" ]; then
        nohup python3 "$script_path" > /dev/null 2>&1 &
        echo -e "\033[1;32m$script_name 启动成功\033[0m"
    else
        echo -e "\033[1;33m$script_name 已经在运行 (PID: $(eval echo \$$pid_var))\033[0m"
    fi
}

# 停止单个脚本
stop_script() {
    local script_name=$1
    local pid_var=$2

    local pid=$(eval echo \$$pid_var)
    if [ -n "$pid" ]; then
        kill "$pid"
        echo -e "\033[1;31m$script_name 已停止\033[0m"
    else
        echo -e "\033[1;33m$script_name 未在运行\033[0m"
    fi
}

while true; do
    check_status
    echo "请选择操作："
    echo "1) 启动 微信命令"
    echo "2) 停止 微信命令"
    echo "3) 启动 TG命令"
    echo "4) 停止 TG命令"
    echo "5) 退出"
    read -rp "输入选项 (1-5): " choice

    case $choice in
        1) start_script "wx.py" "$WX_SCRIPT" WX_PID ;;
        2) stop_script "wx.py" WX_PID ;;
        3) start_script "nbabot.py" "$NBA_SCRIPT" NBA_PID ;;
        4) stop_script "nbabot.py" NBA_PID ;;
        5) echo "退出管理脚本"; exit 0 ;;
        *) echo -e "\033[1;33m无效选项，请输入 1-5\033[0m" ;;
    esac

    echo ""
done
