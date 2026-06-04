# Codex Keepalive & Status Monitor / Codex 多账号自动保活与额度状态监控

---

## English

A command-line tool for managing and monitoring OpenAI Codex CLI client accounts. It automates keepalive triggers and maintains a local cache of quota metrics to display during shell startup.

### Features
1. **Quota Keepalive**: Triggers execution requests via background cron tasks to lock rate-limit cycles before they expire.
2. **Tmux Isolation**: Spawns headless tmux sessions to isolate Codex processes.
3. **Local Metric Caching**: Periodically updates a local cache (`status_cache`) every 3 hours. Shell initialization scripts read directly from this cache to avoid startup latency.
4. **Login Warning**: Detects unauthenticated/logged-out accounts and writes alerts to `state/warning` for shell initialization scripts to display.
5. **Multi-Account Discovery**: Scans `~/.bashrc` to parse custom alias configurations using `HOME` or `CODEX_HOME`.

### Requirements
- **OS**: Linux / macOS
- **Dependencies**: Tmux, Python 3.6+
- **Codex CLI**: Node.js/NVM environment with the `codex` command.

### Configurations
Configurations are defined in `config.toml`:

| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `enable_daily_keepalive` | Boolean | `true` | Enable background keepalive runs. |
| `enable_terminal_snapshot`| Boolean | `true` | Render colorized quota bars in terminal startup. |
| `enable_login_warning` | Boolean | `true` | Display warning messages for logged-out accounts. |
| `discover_aliases` | Boolean | `true` | Discover `HOME` and `CODEX_HOME` aliases from `~/.bashrc`. |

---

## 中文

用于管理与监控 OpenAI Codex CLI 客户端的命令行工具。通过后台定时任务执行保活逻辑，并缓存额度数据以供终端启动时读取。

### 功能说明
1. **额度自动保活**：定时通过后台执行非交互式 `codex exec`，以激活并锁定额度周期，防止滑动周期过期。
2. **Tmux 隔离环境**：通过独立的无界面 tmux 会话运行 Codex 客户端，隔离前台交互。
3. **本地状态缓存**：默认每 3 小时通过 cron 触发更新本地缓存文件 (`status_cache`)。终端启动脚本直接读取该缓存，消除实时查询带来的网络延迟。
4. **登录失效警报**：自动识别掉线账户，将异常写入 `state/warning`，并在终端启动时高亮提醒。
5. **多账号解析**：扫描 `~/.bashrc` 中的别名定义，自动支持基于 `HOME` 或 `CODEX_HOME` 的多账户环境。

### 系统要求
- **操作系统**：Linux / macOS
- **依赖软件**：Tmux, Python 3.6+
- **Codex 客户端**：已安装并配置 Node.js/NVM 环境，且 `codex` 命令可用。

### 配置参数
配置文件为 `config.toml`：

| 配置键 | 类型 | 默认值 | 描述 |
| :--- | :--- | :--- | :--- |
| `enable_daily_keepalive` | 布尔值 | `true` | 是否启用后台保活检测。 |
| `enable_terminal_snapshot`| 布尔值 | `true` | 是否在终端启动时显示彩色额度进度条。 |
| `enable_login_warning` | 布尔值 | `true` | 是否在终端启动时提示未登录账户。 |
| `discover_aliases` | 布尔值 | `true` | 是否从 `~/.bashrc` 自动扫描 `HOME` 或 `CODEX_HOME` 别名。 |
