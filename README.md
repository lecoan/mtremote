# MTRemote (mtr)

MTRemote 是一个专为 AI Infra 和 Python/C++ 混合开发设计的命令行工具。它允许你在本地修改代码，通过简单的 `mtr` 前缀，自动将代码同步到远端 GPU 服务器并执行命令，同时保留本地的交互体验（实时日志、颜色高亮、Ctrl+C 支持）。

## 🚀 特性

*   **多服务器管理**：通过配置文件管理多个 GPU 节点，支持默认服务器。
*   **智能同步**：默认使用 `rsync` 进行增量同步，速度极快；支持排除特定文件（如 checkpoints）。
*   **实时交互**：远端执行的 stdout/stderr 实时流式回显，支持 PTY，完美支持 `ipython`, `pdb` 等交互式工具。
*   **零侵入**：只需在现有命令前加上 `mtr`。

## 📦 安装

推荐使用 `uv` 或 `pipx` 安装：

```bash
uv tool install mtremote
# 或者
pip install mtremote
```

*注意：需要在本地安装 `rsync` (macOS/Linux 自带) 以获得最佳性能。*

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
servers:
  gpu-node:
    host: "192.168.1.100"
    user: "your_username"
    key_filename: "~/.ssh/id_rsa"
    remote_dir: "/home/your_username/projects/my-project"
```

### 3. 运行命令

现在，你可以在本地直接运行远程命令：

```bash
# 同步代码并在 gpu-node 上运行 python train.py
mtr python train.py --epochs 10

# 指定特定服务器
mtr -s prod-node python train.py

# 仅同步代码，不执行命令
mtr --sync-only  # (Coming soon)
# 实际上可以通过 mtr echo "Synced" 达到类似效果
```

## 📖 配置详解

请参考 [examples/config.yaml](examples/config.yaml) 获取完整的配置示例，包括：
*   全局排除文件设置 (`exclude`)
*   密码认证 (不推荐)
*   SFTP 模式 (用于无 rsync 环境)

## 🤝 贡献

欢迎提交 Issue 和 PR！

---
License: MIT
