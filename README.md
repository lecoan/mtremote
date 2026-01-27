# MTRemote (mtr)

MTRemote 是一个专为 AI Infra 和 Python/C++ 混合开发设计的命令行工具。它允许你在本地修改代码，通过简单的 `mtr` 前缀，自动将代码同步到远端 GPU 服务器并执行命令，同时保留本地的交互体验（实时日志、颜色高亮、Ctrl+C 支持）。

## 🚀 核心特性

*   **多服务器管理**：通过配置文件管理多个 GPU 节点，支持默认服务器 (Implicit/Explicit)。
*   **智能同步引擎**：
    *   **Rsync (推荐)**：调用系统 `rsync`，支持增量同步，速度极快。支持 `sshpass` 自动处理密码认证。
    *   **SFTP (兼容)**：纯 Python 实现，适用于无 `rsync` 的环境，配置简单。
*   **双模式交互 (Dual-Mode Interaction)**：
    *   **交互模式 (Interactive)**：自动检测 TTY，支持 PTY 分配、Raw Mode、Rich UI 动画。完美支持 `vim`, `ipython`, `pdb`, `htop`。
    *   **批处理模式 (Batch)**：当被脚本调用或重定向时自动切换。禁用 PTY 和动画，输出纯净文本，适合 AI Agent 集成或 CI/CD。
*   **环境预设 (Pre-cmd)**：支持在执行命令前自动加载环境（如 `conda activate`, `source .env`）。
*   **零侵入**：只需在现有命令前加上 `mtr`。

## 📦 安装

推荐使用 `uv` 或 `pipx` 安装：

```bash
uv tool install mtremote
# 或者
pip install mtremote
```

*注意：使用 rsync 模式推荐在本地安装 `rsync` (macOS/Linux 自带)。如果使用密码认证且坚持用 rsync，需安装 `sshpass`。*

## 🛠️ 快速开始

### 1. 初始化配置

在你的项目根目录下运行：

```bash
mtr --init
```

这将在 `.mtr/config.yaml` 生成配置文件。

### 2. 编辑配置

编辑 `.mtr/config.yaml`，填入你的服务器信息：

```yaml
defaults:
  sync: "rsync"  # 或 "sftp"
  exclude: [".git/", "__pycache__/"]

servers:
  gpu-node:
    host: "192.168.1.100"
    user: "your_username"
    key_filename: "~/.ssh/id_rsa"
    remote_dir: "/home/your_username/projects/my-project"
    pre_cmd: "source ~/.bashrc && conda activate pytorch_env"
```

### 3. 运行命令

现在，你可以在本地直接运行远程命令：

```bash
# 同步代码并在 gpu-node 上运行 python train.py
mtr python train.py --epochs 10

# 进入远程交互式 Shell (支持 Tab 补全和颜色)
mtr bash

# 使用 ipython 调试
mtr ipython

# 指定特定服务器
mtr -s prod-node python train.py
```

## 📖 高级用法

### 1. 强制批处理模式 (--no-tty)
如果你在终端中运行但希望获得纯文本输出（不想要进度条或颜色控制字符），可以使用 `--no-tty`：

```bash
mtr --no-tty python train.py > log.txt
```

### 2. 使用 SFTP 模式
如果本地或远程无法使用 rsync，可以在配置中指定 `sync: sftp`：

```yaml
servers:
  win-server:
    host: "10.0.0.9"
    sync: "sftp"
    password: "secret_password"
```

### 3. 密码认证
支持 SSH 密码认证，但推荐使用 SSH Key。
*   **SFTP**: 原生支持密码。
*   **Rsync**: 需要本地安装 `sshpass` 工具才能使用密码认证。

## 🤖 AI Agent 集成指南

MTRemote 非常适合作为 AI Agent (如 OpenCode, LangChain Agents) 的底层执行工具。

### 为什么适合 Agent?
1.  **自动同步**：Agent 只需要修改本地文件，`mtr` 负责将修改“热更新”到运行环境。
2.  **纯净输出**：使用 `--no-tty` 参数，`mtr` 会禁用 ANSI 颜色代码、进度条动画和交互式 Shell 提示符，只返回最纯粹的 stdout/stderr。这大大降低了 Agent 解析日志的难度。
3.  **状态透传**：`mtr` 的退出代码 (Exit Code) 与远程命令完全一致。Agent 可以通过 `$?` 判断远程任务是否成功。

### 推荐调用方式

Agent 在调用 `mtr` 时，**强烈建议**始终加上 `--no-tty` 参数。

```python
import subprocess

def run_remote_command(cmd):
    # 使用 --no-tty 确保输出无干扰
    full_cmd = ["mtr", "--no-tty"] + cmd.split()
    
    result = subprocess.run(
        full_cmd, 
        capture_output=True, 
        text=True
    )
    
    if result.returncode != 0:
        return f"Error: {result.stderr}"
    return result.stdout

# 示例：Agent 修改完代码后运行测试
output = run_remote_command("python tests/test_model.py")
```

## 📖 配置详解

请参考 [examples/config.yaml](examples/config.yaml) 获取完整的配置示例。

## 🤝 贡献

欢迎提交 Issue 和 PR！

---
License: MIT

