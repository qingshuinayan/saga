@echo off
chcp 65001 >nul
echo ========================================
echo   Saga - 服务管理器
echo ========================================
echo.
echo ⚠️  注意：Windows 服务功能为可选高级功能
echo    常规使用请直接运行 run_saga.bat
echo.
echo 请选择操作：
echo.
echo 1. 📦 安装为 Windows 服务（开机自启动）
echo 2. ▶️  启动 Saga 服务
echo 3. ⏸️  停止 Saga 服务
echo 4. 🗑️  卸载 Windows 服务
echo 5. ℹ️  查看服务状态
echo 6. 🚀 常规启动 Saga（推荐）
echo 0. 📖  查看帮助说明
echo.
set /p choice=请输入数字选择 (0-6):

if "%choice%"=="1" (
    echo.
    echo ========================================
    echo   安装 Windows 服务
    echo ========================================
    echo.
    echo 前置要求：
    echo 1. 安装 pywin32：pip install pywin32
    echo 2. 管理员权限运行此脚本
    echo.
    set /p confirm=确认已满足要求？(Y/N):
    if /i "%confirm%"=="Y" (
        if exist install_windows_service.py (
            echo 正在安装 Saga 服务...
            python install_windows_service.py install
            if %errorlevel%==0 (
                sc config SagaPersonalAssistant start= auto
                echo ✅ 服务安装完成，已设置为自动启动
                echo    可以通过服务管理器或选项 2 启动服务
            ) else (
                echo ❌ 服务安装失败，请检查错误信息
            )
        ) else (
            echo ❌ 找不到 install_windows_service.py
            echo    此功能需要额外的服务安装脚本
            echo    建议使用 run_saga.bat 启动应用
        )
    )
    pause
) else if "%choice%"=="2" (
    echo.
    echo 正在启动 Saga 服务...
    net start SagaPersonalAssistant
    if %errorlevel%==0 (
        echo ✅ 服务启动完成
        echo    访问地址: http://localhost:8501
    ) else (
        echo ❌ 服务启动失败
        echo    可能原因：服务未安装或已运行
    )
    pause
) else if "%choice%"=="3" (
    echo.
    echo 正在停止 Saga 服务...
    net stop SagaPersonalAssistant
    if %errorlevel%==0 (
        echo ✅ 服务停止完成
    ) else (
        echo ❌ 服务停止失败
        echo    可能原因：服务未安装或未运行
    )
    pause
) else if "%choice%"=="4" (
    echo.
    echo 正在卸载 Saga 服务...
    if exist install_windows_service.py (
        python install_windows_service.py remove
        if %errorlevel%==0 (
            echo ✅ 服务卸载完成
        ) else (
            echo ❌ 服务卸载失败
        )
    ) else (
        echo ❌ 找不到 install_windows_service.py
    )
    pause
) else if "%choice%"=="5" (
    echo.
    echo ========================================
    echo   Saga 服务状态
    echo ========================================
    echo.
    sc query SagaPersonalAssistant
    echo.
    echo 如果服务未安装，请使用选项 1 安装
    pause
) else if "%choice%"=="6" (
    echo.
    echo 正在启动 Saga 应用...
    echo 使用 Ctrl+C 停止应用
    echo.
    call run_saga.bat
) else if "%choice%"=="0" (
    cls
    echo ========================================
    echo   Saga - 帮助说明
    echo ========================================
    echo.
    echo 📖 使用指南：
    echo.
    echo 1. 常规启动（推荐）：
    echo    双击运行 run_saga.bat
    echo    或在命令行执行：streamlit run main.py
    echo.
    echo 2. Windows 服务（高级）：
    echo    - 适合需要开机自启动的场景
    echo    - 需要管理员权限和 pywin32
    echo    - 服务在后台运行，无命令行窗口
    echo.
    echo 3. 访问应用：
    echo    浏览器打开：http://localhost:8501
    echo.
    echo 4. 配置文件：
    echo    - config.yaml：主配置文件
    echo    - config.yaml.example：配置模板
    echo.
    echo 5. 数据目录：
    echo    - data/：所有数据存储（数据库、向量库、上传文件）
    echo.
    echo 6. 日志文件：
    echo    - logs/：运行日志目录
    echo.
    echo 7. 故障排除：
    echo    - 检查 logs/saga.log 查看详细错误
    echo    - 确认 config.yaml 配置正确
    echo    - 验证 API 密钥有效
    echo.
    echo 📚 更多信息请参考 README.md
    echo.
    pause
) else (
    echo.
    echo ❌ 无效选择，请输入 0-6 的数字
    pause
)
