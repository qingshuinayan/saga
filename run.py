import os
import sys
import subprocess
import webbrowser
from time import sleep

# --- 检查和创建必要目录 ---
# 确保项目结构中定义的所有目录都存在
required_dirs = [
    "logs",
    "pages", 
    "prompts", 
    "utils", 
    "data",
    "data/uploads",
    "data/chroma_db", 
    "data/bm25_indices",
    "data/backups"
]

def create_directories():
    """检查并创建项目所需的所有目录。"""
    for dir_path in required_dirs:
        if not os.path.exists(dir_path):
            print(f"创建目录: {dir_path}")
            os.makedirs(dir_path)

def main():
    """
    启动Saga个人知识助手Streamlit应用。
    """
    # 确保我们在正确的项目根目录下运行
    project_root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_root)
    
    # 1. 创建所有必需的目录
    create_directories()

    # 2. 定义Streamlit启动命令
    main_app_file = "main.py"
    command = [
        sys.executable,  # 使用当前Python解释器
        "-m",
        "streamlit",
        "run",
        main_app_file,
        "--server.port", "8501",
        "--server.address", "0.0.0.0" # 允许局域网访问
    ]

    print("=" * 50)
    print("🚀 正在启动 Saga 个人知识助手...")
    print(f"📁 项目根目录: {project_root}")
    print(f"⚙️ 启动命令: {' '.join(command)}")
    print("=" * 50)
    
    try:
        # 启动Streamlit服务
        proc = subprocess.Popen(command)
        
        # 等待一小段时间让服务启动，然后自动打开浏览器
        sleep(3)
        print("🌐 正在尝试在浏览器中打开应用...")
        webbrowser.open("http://localhost:8501")
        
        # 等待进程结束
        proc.wait()

    except FileNotFoundError:
        print("\n❌ 错误: 'streamlit' 命令未找到。")
        print("请确保您已经安装了Streamlit: pip install streamlit")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n🛑 用户请求关闭，正在停止服务...")
        proc.terminate()
    except Exception as e:
        print(f"\n🔥 启动过程中发生未知错误: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
