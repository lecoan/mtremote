MTRemote (mtr) 需求规格与设计文档
1. 项目概述
MTRemote 是一个用于 AI Infra 开发的 CLI 工具，旨在简化“本地开发、远端执行”的工作流。它允许开发者在本地修改代码，通过简单的命令前缀 mtr，自动将代码同步到远端服务器并在其上执行命令，同时保持本地的交互体验。
2. 核心功能需求
2.1 多服务器配置与管理
*   多环境支持：支持在配置文件中定义多个服务器节点（如 dev-gpu, prod-train）。
*   默认服务器策略：
    1.  若 CLI 指定 -s/--server，使用指定服务器。
    2.  若未指定，检查配置中是否存在 default 字段。
    3.  若无 default 字段，自动选择 servers 列表中的第一个定义的服务器。
*   认证管理：支持在配置文件中显式指定 SSH 私钥路径 (key_filename) 或 密码 (password)，不依赖系统 SSH Agent。
2.2 智能代码同步 (Sync Engine)
*   双引擎支持：
    *   *Rsync (推荐)*：调用系统 rsync 命令，通过 SSH 隧道传输，支持增量同步，速度快。
    *   *SFTP (兼容)*：基于 paramiko 实现的纯 Python 同步，用于无 rsync 的环境。
*   可配置性：支持在全局或单台服务器级别指定同步引擎。
*   文件过滤：支持忽略特定文件（如 .git, __pycache__），支持 .mtrignore 或配置字段。
2.3 远程执行 (Remote Execution)
*   命令透传：mtr python train.py --lr 0.01 -> 远端执行 python train.py --lr 0.01。
*   环境上下文：支持指定远程工作目录 (remote_dir)。
*   实时流式输出：远端的 stdout 和 stderr 必须实时回显到本地，支持颜色代码。
*   交互性：支持 PTY 分配，允许运行交互式命令（如 ipython, pdb）。
---
3. 系统设计与模块划分
我们将系统划分为四个核心模块，这也将是 TDD 的测试边界：
3.1 配置模块 (mtr.config)
负责加载、合并和校验配置。
*   输入：CLI 参数、./.mtr/config.yaml、~/.config/mtr/config.yaml。
*   逻辑：
    *   配置层级合并（Project Config 覆盖 User Config）。
    *   解析服务器列表，确定 Target Host。
*   *数据结构 (Config Schema)*：
        defaults:
      sync: "rsync" # or "sftp"
      exclude: [".git", "__pycache__"]
    servers:
      gpu-01: # 第一个即为隐式默认
        host: "192.168.1.10"
        user: "dev"
        key_filename: "~/.ssh/id_rsa"
        remote_dir: "/data/codes/project_x"
      
      fallback-node:
        host: "10.0.0.5"
        user: "dev"
        password: "secret_password"
        sync: "sftp" # 覆盖默认配置
    
3.2 连接模块 (mtr.ssh)
负责底层的 SSH 连接管理。
*   基于 paramiko 封装。
*   提供 connect(), exec_command_stream() 接口。
*   处理连接异常和认证失败。
3.3 同步模块 (mtr.sync)
定义 BaseSyncer 抽象基类，统一接口 sync(local_dir, remote_dir, exclude_list)。
*   RsyncSyncer: 构造 subprocess 调用系统命令。
*   SftpSyncer: 遍历文件树，对比 mtime/size，使用 paramiko sftp 上传。
3.4 CLI 入口 (mtr.cli)
*   基于 click 库。
*   负责参数解析、调用 Config -> Connect -> Sync -> Exec 流程。
---
4. TDD 测试策略与目录规划
在编写任何业务代码前，我们将按照以下结构建立测试目录。
4.1 测试目录结构
tests/
├── __init__.py
├── conftest.py             # 通用 Fixtures (模拟配置文件、模拟文件系统)
├── unit/                   # 单元测试 (Mock 外部依赖)
│   ├── test_config.py      # 重点：测试配置加载优先级、默认服务器选择逻辑
│   ├── test_sync_rsync.py  # 测试 Rsync 命令生成逻辑 (不实际传输)
│   ├── test_sync_sftp.py   # 测试文件过滤逻辑、差异对比逻辑 (Mock SFTP)
│   └── test_ssh.py         # 测试 SSH 客户端封装 (Mock paramiko)
└── integration/            # 集成/功能测试
    └── test_cli_flow.py    # 测试 CLI 参数解析与流程串联
4.2 关键测试用例 (Test Cases)
1. 配置加载测试 (test_config.py)
*   test_load_default_server_explicit: 当配置中有 default 字段时，应选中该 Server。
*   test_load_default_server_implicit_first: 当无 default 字段时，应选中 servers 列表的第一个。
*   test_server_override: CLI -s 参数应覆盖配置文件的默认值。
*   test_auth_config: 验证 Key 和 Password 都能被正确读取。
2. 同步逻辑测试 (test_sync_*.py)
*   test_rsync_command_generation: 验证生成的 rsync 命令是否包含正确的 exclude 参数和路径。
*   test_sftp_should_sync: 给定本地和远端文件状态（大小/时间），验证 should_sync 逻辑是否正确判断需要更新的文件。
3. SSH 执行测试 (test_ssh.py)
*   test_exec_stream: Mock paramiko 的 stdout，验证回调函数能否正确接收流式数据。
