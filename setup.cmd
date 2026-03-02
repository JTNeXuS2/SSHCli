@echo off
cd %~dp0
chcp 65001>nul

pip install paramiko

timeout /t 3
