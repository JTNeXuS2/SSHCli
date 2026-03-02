@echo off
cd %~dp0
chcp 65001>nul

python SSHCli.py

timeout /t 3
