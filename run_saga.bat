@echo off
chcp 65001
echo 正在启动 Saga 个人知识助手...

:: 切换到当前脚本所在的目录，以确保项目路径正确
cd /d %~dp0

:: 使用 python 启动 run.py
python run.py
