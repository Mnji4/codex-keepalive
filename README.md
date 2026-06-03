# Codex Keepalive & Status Monitor / Codex 多账号自动保活与额度状态监控

[English](#english) | [中文](#中文)

---

## English

A lightweight tool designed for developers managing single or multiple accounts on the OpenAI Codex CLI client. It ensures your sliding weekly rate limits are kept active seamlessly, keeps track of account metrics, and prints beautiful, instant quota status tables upon opening new terminal windows—without any startup delay.

### 🌟 Key Features
- **Maximize Quota Utilization (Intelligent Keepalive)**: Especially in multi-account setups, this tool ensures that each account's sliding weekly quota is activated (locked into a new cycle) immediately upon reset, preventing precious limits from sitting idle and going to waste. It dynamically skips wakeups if the countdown timer is already running.
  - *Custom Hours-based Interval*: You can customize the check frequency via `keepalive_interval_hours` in `config.toml`. The check runs silently in the background and exits in 10ms if the configured interval has not yet elapsed, preventing CPU overhead.
- **TUI Session Reuse (No Dialog Clutter)**: Emulates keyboard macros (`Esc -> Up -> Enter`) to edit the last message in an existing `keepalive` chat room, avoiding polluting your chat list. 
  - *No manual setup required*: The script will automatically send a new message to create the `keepalive` chat room if it does not find one.
- **Zero-Latency Shell Startup**: Querying metrics for each account takes **15-20 seconds** (e.g. ~75 seconds for 4 accounts). To avoid blocking your shell, this tool runs in the background and saves a local status cache. Opening a terminal displays the cache instantly (0ms delay).
- **Aesthetic Terminal Dashboard**: Renders colorized quota meters and progress bars directly on terminal startup (green for healthy, yellow for warnings, red for depleted).
- **Broken Connection Alerts**: Logged-out accounts trigger warnings and write to `~/.codex_warning`, alerting you to log in manually at shell launch.

### 🚀 Usage Guide (Single vs Multi Account)

#### Single Account Usage (Default)
If you only run one default instance of Codex (configured at your root user directory), **no configuration is needed**. The installer will automatically register and monitor your primary `codex` command.

#### Multi Account Usage
If you are managing multiple accounts, define your aliases in your `~/.bashrc` before running the installer. E.g.:
```bash
alias codex0="HOME=~/.codex_user0 codex"
alias codex1="HOME=~/.codex_user1 codex"
alias codex2="HOME=~/.codex_user2 codex"
```
The script will dynamically discover these alias commands and monitor all accounts accordingly.

### ⚙️ Config & Deleting Features

You can configure feature toggles inside `~/codex-keepalive/config.toml`:

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `enable_daily_keepalive` | Boolean | `true` | Enable/Disable automatic keepalive check runs. |
| `keepalive_interval_hours`| Integer | `24` | Keepalive check interval in hours. Keep this short (e.g., 24h or less) in multi-account setups to lock new weekly cycles instantly on reset, preventing quota waste. |
| `enable_terminal_snapshot`| Boolean | `true` | Show colorized progress snapshot on terminal startup. |
| `enable_login_warning` | Boolean | `true` | Show high-visibility warnings for logged-out accounts. |

#### How to Turn Off or Delete Specific Features
- If you set `enable_terminal_snapshot = false` or `enable_login_warning = false` in `config.toml`, **the script will automatically clean up the local cached files** (`~/.codex_status_cache` and `~/.codex_warning`), immediately stopping the terminal output.

#### Complete Uninstall & Cleanup
To completely remove this tool and all local traces from your system:
1. Delete the installation directory:
   ```bash
   rm -rf ~/codex-keepalive
   ```
2. Delete cached state, log, and alert files:
   ```bash
   rm -f ~/.codex_status_cache ~/.codex_warning ~/.codex_keepalive.state ~/.codex_keepalive.log
   ```
3. Open `~/.bashrc` and delete the lines appended at the end of the file (under the `# Codex Auto Keepalive Trigger` header, including the `codex_status` alias).

---

## 中文

为 OpenAI Codex CLI 命令行客户端用户量身定制的轻量级多账号管理工具。支持单账号/多账号保活（按需激活）、本地会话防污染、掉线提醒以及免卡顿的终端打开实时额度进度条渲染。

### 🌟 核心功能
- **最大化额度利用率（按需智能唤醒）**：由于每周额度是滑动重置的，特别是在多账户情况下，该工具能确保每个账号的每周额度（Weekly limit）在刷新重置的第一时间被自动激活（锁定新一轮周期），避免因新周期未开启而导致宝贵的限额被白白闲置和浪费。如果滑动倒计时已经运行，则会自动跳过唤醒。
  - *自定义检测周期*：您可以通过修改 `config.toml` 中的 `keepalive_interval_hours` 来自定义保活检测的间隔时间（以小时为单位）。该任务在后台静默执行，若未到指定间隔则会在 10ms 内秒退，绝不占用系统资源与 CPU 算力。
- **本地会话防污染**：唤醒消息通过 Tmux 键盘宏（`Esc -> Up -> Enter`）在现有的 `keepalive` 对话中覆盖编辑并发送，不在本地 `/resume` 会话列表中留下任何历史垃圾。
  - *无需手动创建对话*：若脚本未检索到名为 `keepalive` 的会话，**会自动发送新消息进行创建**，无须任何前置人工操作。
- **终端启动零延迟**：查询**单个账号状态约需 15-20 秒**（如 4 个账号顺序查询需要约 75 秒）。本工具将查询任务放在后台异步执行并写入本地缓存。每次打开终端仅需 0ms 读取本地快照，绝不拖慢终端启动。
- **精美进度条看板**：在打开终端时自动以原汁原味的彩色进度条展示额度（绿/黄/红三色根据剩余量高亮）。
- **掉登录高亮报警**：自动识别因过期掉登录的账号并生成警报，在您打开终端时予以红字高亮提醒。

### 🚀 单账号与多账号使用指南

#### 单账号使用（默认）
如果您只使用单个默认的 Codex 账号，**无需进行任何配置**。运行安装脚本后，工具会自动绑定并监控您的主 `codex` 账号。

#### 多账号使用
如果您使用多账号，请先在您的 `~/.bashrc` 中配置好对应的命令别名：
```bash
alias codex0="HOME=~/.codex_user0 codex"
alias codex1="HOME=~/.codex_user1 codex"
alias codex2="HOME=~/.codex_user2 codex"
```
完成配置后运行安装脚本，工具将自动扫描并动态解析所有配置的账号。

### ⚙️ 功能开关与删除清理

您可以通过修改 `~/codex-keepalive/config.toml` 来配置功能开关：

| 配置参数 | 类型 | 默认值 | 作用说明 |
| :--- | :--- | :--- | :--- |
| `enable_daily_keepalive` | 布尔值 | `true` | 是否启用后台自动保活触发任务。 |
| `keepalive_interval_hours`| 整数 | `24` | 自动保活检测的时间间隔（小时）。多账户情况下建议保持较短间隔（如 24 小时或更低），以便在周额度重置时立刻发送保活消息锁定新周期，防止额度闲置浪费。 |
| `enable_terminal_snapshot`| 布尔值 | `true` | 是否在终端启动时打印彩色额度进度条快照。 |
| `enable_login_warning` | 布尔值 | `true` | 是否在终端启动时提示掉登录的账号。 |

#### 如何关闭或删除特定功能
- 如果您在 `config.toml` 中将 `enable_terminal_snapshot` 或 `enable_login_warning` 设为 `false`，**脚本将在下一次运行时自动删除对应的本地缓存文件**（`~/.codex_status_cache` 或 `~/.codex_warning`），从而立刻停止在终端启动时显示相应信息。

#### 彻底卸载与清理垃圾
如果您想彻底删除此工具及系统上的所有本地痕迹：
1. 删除安装目录：
   ```bash
   rm -rf ~/codex-keepalive
   ```
2. 删除本地缓存、状态、日志和警报文件：
   ```bash
   rm -f ~/.codex_status_cache ~/.codex_warning ~/.codex_keepalive.state ~/.codex_keepalive.log
   ```
3. 打开 `~/.bashrc`，删除文件末尾追加的命令别名及 hooks 脚本块（在 `# Codex Auto Keepalive Trigger` 注释之后的所有内容）。

---
