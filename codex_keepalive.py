#!/usr/bin/env python3
import os
import sys
import re
import time
import datetime
import subprocess
import threading
import random
import shutil
import json

USER_HOME = os.path.expanduser("~")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(SCRIPT_DIR, "state")
os.makedirs(STATE_DIR, exist_ok=True)

LOG_FILE = os.path.join(STATE_DIR, "keepalive.log")
results = {}
lock = threading.Lock()

def log_message(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted)
    with open(LOG_FILE, "a") as f:
        f.write(formatted + "\n")

def check_log_size():
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f:
                lines = f.readlines()
            if len(lines) > 500:
                with open(LOG_FILE, "w") as f:
                    f.writelines(lines[-100:])
        except Exception:
            pass

def load_config():
    config = {
        "enable_daily_keepalive": "true",
        "keepalive_chat_name": "keepalive",
        "enable_terminal_snapshot": "true",
        "enable_login_warning": "true",
        "discover_aliases": "true",
        "nvm_dir": os.path.join(USER_HOME, ".nvm")
    }
    config_path = os.path.join(SCRIPT_DIR, "config.toml")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        config[k] = v
        except Exception:
            pass
    return config

def cleanup_files(config):
    if config.get("enable_terminal_snapshot", "true").lower() != "true":
        cache_file = os.path.join(STATE_DIR, "status_cache")
        if os.path.exists(cache_file):
            try:
                os.remove(cache_file)
            except Exception:
                pass
                
    if config.get("enable_login_warning", "true").lower() != "true":
        warning_file = os.path.join(STATE_DIR, "warning")
        if os.path.exists(warning_file):
            try:
                os.remove(warning_file)
            except Exception:
                pass

def discover_accounts(config):
    accounts = [
        ("HOME", USER_HOME, os.path.join(USER_HOME, ".codex"), "codex", "Primary Account (codex)")
    ]
    if config.get("discover_aliases", "true").lower() != "true":
        return accounts
        
    bashrc_path = os.path.join(USER_HOME, ".bashrc")
    if not os.path.exists(bashrc_path):
        return accounts
        
    try:
        with open(bashrc_path, "r") as f:
            content = f.read()
            
        pattern = re.compile(r'alias\s+([a-zA-Z0-9_-]+)\s*=\s*["\'](HOME|CODEX_HOME)=([^\s"\']+) codex["\']')
        matches = pattern.findall(content)
        
        seen_dirs = {os.path.join(USER_HOME, ".codex")}
        for cmd_name, env_name, path_val in matches:
            full_path = os.path.realpath(os.path.expanduser(path_val))
            if env_name == "HOME":
                codex_dir = os.path.join(full_path, ".codex")
            else:
                codex_dir = full_path
                
            if codex_dir not in seen_dirs:
                seen_dirs.add(codex_dir)
                accounts.append((env_name, full_path, codex_dir, cmd_name, f"Alias Account ({cmd_name})"))
    except Exception:
        pass
        
    return accounts

def parse_metric(metric_name, screen):
    clean_screen = screen.replace("│", " ")
    pattern_same_line = re.compile(
        re.escape(metric_name) + r':\s*\[[^\]]*\]\s*(\d+%\s*left)\s*\(resets\s*([^\)]+)\)',
        re.IGNORECASE
    )
    m = pattern_same_line.search(clean_screen)
    if m:
        return m.group(1).strip(), m.group(2).strip().replace('\n', ' ')
        
    pattern_cross_line = re.compile(
        re.escape(metric_name) + r':\s*\[[^\]]*\]\s*(\d+%\s*left)(?:\s*\n\s*)\(resets\s*([^\)]+)\)',
        re.IGNORECASE
    )
    m = pattern_cross_line.search(clean_screen)
    if m:
        return m.group(1).strip(), m.group(2).strip().replace('\n', ' ')
        
    pattern_only_limit = re.compile(
        re.escape(metric_name) + r':\s*\[[^\]]*\]\s*(\d+%\s*left)',
        re.IGNORECASE
    )
    m = pattern_only_limit.search(clean_screen)
    if m:
        return m.group(1).strip(), "unknown"
        
    return None, None

def parse_reset_time_to_datetime(reset_str):
    if not reset_str or "unknown" in reset_str or "please wait" in reset_str or "未知" in reset_str:
        return None
        
    now = datetime.datetime.now()
    year = now.year
    
    m = re.match(r'(\d{1,2}):(\d{2})\s+on\s+(\d+)\s+([A-Za-z]+)', reset_str.strip())
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        day = int(m.group(3))
        month_str = m.group(4)[:3].lower()
        
        months = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
        }
        month = months.get(month_str, now.month)
        try:
            dt = datetime.datetime(year, month, day, hour, minute)
            if now.month == 12 and month == 1:
                dt = datetime.datetime(year + 1, month, day, hour, minute)
            return dt
        except:
            return None
            
    m = re.match(r'(\d{1,2}):(\d{2})', reset_str.strip())
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        return datetime.datetime(year, now.month, now.day, hour, minute)
        
    return None

def parse_reset_time_to_hours(reset_str, is_weekly):
    if not reset_str or "unknown" in reset_str.lower() or "please wait" in reset_str.lower() or "未知" in reset_str:
        return 168.0 if is_weekly else 5.0
        
    now = datetime.datetime.now()
    
    if is_weekly:
        m = re.match(r'(\d{1,2}):(\d{2})\s+on\s+(\d+)\s+([A-Za-z]+)', reset_str.strip())
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2))
            day = int(m.group(3))
            month_str = m.group(4)[:3].lower()
            
            months = {
                "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
            }
            month = months.get(month_str, now.month)
            try:
                dt = datetime.datetime(now.year, month, day, hour, minute)
                if now.month == 12 and month == 1:
                    dt = datetime.datetime(now.year + 1, month, day, hour, minute)
                delta = (dt - now).total_seconds() / 3600.0
                return max(0.1, delta)
            except:
                return 168.0
        return 168.0
    else:
        m = re.match(r'(\d{1,2}):(\d{2})', reset_str.strip())
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2))
            try:
                dt = datetime.datetime(now.year, now.month, now.day, hour, minute)
                if dt < now:
                    dt += datetime.timedelta(days=1)
                delta = (dt - now).total_seconds() / 3600.0
                return max(0.05, delta)
            except:
                return 5.0
        return 5.0

def fetch_account_metrics_thread(env_name, env_val, codex_dir, cmd_name, label, config, index):
    time.sleep(1.0 * index)
    clean_label = re.sub(r'[^a-zA-Z0-9_]', '', label.replace(' ', '_'))
    session_name = f"keepalive_check_{clean_label}"
    
    subprocess.run(f"tmux kill-session -t {session_name} 2>/dev/null", shell=True)
    subprocess.run(f"tmux new-session -d -s {session_name} bash", shell=True)
    time.sleep(1)
    
    nvm_dir = config.get("nvm_dir", os.path.join(USER_HOME, ".nvm"))
    nvm_cmd = f'export NVM_DIR="{nvm_dir}" && [ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"'
    run_cmd = f"{env_name}={env_val} codex"

    subprocess.run(f"tmux send-keys -t {session_name} '{nvm_cmd}' C-m", shell=True)
    time.sleep(0.5)
    subprocess.run(f"tmux send-keys -t {session_name} '{run_cmd}' C-m", shell=True)
    
    ready = False
    for _ in range(60):
        time.sleep(0.5)
        res = subprocess.run(f"tmux capture-pane -t {session_name} -p", shell=True, stdout=subprocess.PIPE, text=True)
        if "Collaboration mode:" in res.stdout or "Session:" in res.stdout or ("›" in res.stdout and "Booting" not in res.stdout):
            ready = True
            break
            
    subprocess.run(f"tmux send-keys -t {session_name} '/status' C-m", shell=True)
    time.sleep(6)
    
    email = "unknown"
    metrics = {}
    screen = ""
    
    for attempt in range(4):
        if attempt > 0:
            time.sleep(3)
            
        subprocess.run(f"tmux send-keys -t {session_name} C-u", shell=True)
        time.sleep(0.5)
        subprocess.run(f"tmux send-keys -t {session_name} '/status' C-m", shell=True)
        time.sleep(1.5)
        
        res = subprocess.run(f"tmux capture-pane -t {session_name} -p", shell=True, stdout=subprocess.PIPE, text=True)
        screen = res.stdout
        
        email_match = re.search(r'Account:\s+([^\s(]+)', screen)
        if email_match:
            email = email_match.group(1).strip()
            
        temp_metrics = {}
        for metric_name in ["5h limit", "Weekly limit", "Usage limit"]:
            limit, reset = parse_metric(metric_name, screen)
            if limit:
                temp_metrics[metric_name] = {"limit": limit, "reset": reset}
                
        if temp_metrics:
            metrics = temp_metrics
            break
            
    subprocess.run(f"tmux kill-session -t {session_name} 2>/dev/null", shell=True)
    
    with lock:
        results[label] = {
            "cmd": cmd_name,
            "email": email,
            "metrics": metrics
        }

def get_random_prose():
    prose_list = [
        "在这个寂静的深夜，屏幕散发着微弱的幽蓝色光芒，一行行代码如同流星般在深邃的夜空中划过。指尖在键盘上轻快地跳跃，敲击声宛如一首无声的夜曲，打破了四周的喧嚣。每一个字符的输入，都是对 logic 与秩序的探索，每一个函数的调用，都在构建一个虚拟而美妙的微观世界。窗外夜色正浓，月光如流水般洒落在窗台上，与室内的灯光交相辉映。在这个由零和一构成的浩瀚宇宙中，思想如同脱缰的野马自由驰骋，跨越了物理的边界，去寻找解决难题的终极答案。这不仅是一次简单的保活测试，更是灵魂在数字荒野中的一次短途旅行，让代码的律动伴随着深夜的静谧，流淌向未知的远方。夜空深邃，繁星闪烁，正如那浩瀚数据海洋中闪烁的每一个智慧火花，指引着前行的路途。",
        "晨曦微露，第一缕阳光穿透薄雾，轻轻拂过街道两旁林立的霓虹招牌。空气中弥漫着泥土与青草的芬芳，宣告着新一天的降临。远处的山峦在晨光中逐渐清晰，轮廓如同一幅淡雅的水墨画，层叠交错，绵延起伏。在这个万物苏醒的时刻，城市的脉搏开始缓缓跳动，行人的脚步声、车辆的喧嚣声交织在一起，奏响了日常的交响乐章。对于追逐梦想的人而言，每一个清晨都是一个新的起点，是拂去昨日疲惫、重新扬帆起航的契机。我们在时间的河流中穿梭，寻找着属于自己的航向，纵使前路漫漫，只要心中有光，便无惧风雨。让这缕清晨的微风带走所有的倦意，在数字世界与现实交织的边缘，用坚实的步伐踏出一条通往未来的宽广道路。",
        "午后阳光正好，透过落地窗洒在斑驳的木质桌面上，折射出温暖而柔和的金黄色光晕。一杯清茶正袅袅升起白雾，茶香在空气中悄然弥漫，带走了一整天伏案工作的疲惫。指尖抚过书页，发出细微而清脆的声响，那墨香与茶香交织在一起，构筑起一个让人心安的静谧角落。在这个快节奏的时代里，能够拥有一段不受打扰的午后时光，静静地思考与阅读，实为一种难得的奢求。每一个字句的跳跃，都在脑海中激荡起层层涟漪，引发对生命、宇宙以及微观世界的无限遐想。生活或许琐碎繁杂，但只要我们愿意驻足片刻，在这一呼一吸之间，便能感受到岁月的静好与生命本真的纯粹，让思绪在这一刻自由地漂浮、沉淀。",
        "秋风拂过，落叶如同一只只金黄色的蝴蝶，在空中轻盈地盘旋、飞舞，最后缓缓铺满林荫小道。踩在上面发出沙沙的声响，那是大自然在季节更替时奏响的独特乐章。仰望天空，天高云淡，瓦蓝得没有一丝杂质，让人心宁神怡。秋天不仅是收获的季节，更是思索与沉淀的时刻。经历了夏天的喧嚣与狂热，大自然在秋天展现出一种宁静而内敛的美。树木褪去了繁华的绿装，以最本真的姿态迎接冬天的洗礼。这就像人生的旅途，在经历了繁华与喧闹之后，终究要回归内心的宁静，去审视自己的所得与所失，在反思中积蓄力量，等待下一个春天的萌芽。这沙沙的落叶声，是岁月沉淀的足迹，也是生命不息的赞歌。"
    ]
    return random.choice(prose_list)

def trigger_keepalive_exec(env_name, env_val, codex_dir, label, config):
    log_message(f"[{label}] Triggering non-interactive keepalive wakeup via codex exec...")
    
    now = datetime.datetime.now()
    year_str = now.strftime("%Y")
    month_str = now.strftime("%m")
    day_str = now.strftime("%d")
    session_dir = os.path.join(codex_dir, "sessions", year_str, month_str, day_str)
    
    existing_files = set()
    if os.path.exists(session_dir):
        try:
            existing_files = set(os.listdir(session_dir))
        except Exception:
            pass
            
    prose = get_random_prose()
    nvm_dir = config.get("nvm_dir", os.path.join(USER_HOME, ".nvm"))
    nvm_cmd = f'export NVM_DIR="{nvm_dir}" && [ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"'
    run_cmd = f"{env_name}={env_val} codex exec \"{prose}\" --skip-git-repo-check"
    full_cmd = f"{nvm_cmd} && {run_cmd}"
    
    try:
        subprocess.run(full_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        log_message(f"[{label}] Codex exec run completed successfully.")
    except subprocess.TimeoutExpired:
        log_message(f"[{label}] Warning: Codex exec run timed out after 60 seconds.")
    except Exception as e:
        log_message(f"[{label}] Error running codex exec: {e}")
        
    new_files = set()
    if os.path.exists(session_dir):
        try:
            new_files = set(os.listdir(session_dir)) - existing_files
        except Exception:
            pass
            
    for f in new_files:
        if f.endswith(".jsonl"):
            f_path = os.path.join(session_dir, f)
            is_keepalive = False
            try:
                if os.path.exists(f_path):
                    with open(f_path, "r", encoding="utf-8") as sf:
                        content = sf.read()
                        if prose in content:
                            is_keepalive = True
            except:
                pass
                
            if is_keepalive:
                try:
                    os.remove(f_path)
                except:
                    pass
                    
                history_file = os.path.join(codex_dir, "history.jsonl")
                if os.path.exists(history_file):
                    m = re.search(r'rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-([a-f0-9-]+)\.jsonl', f)
                    if m:
                        session_id = m.group(1)
                        try:
                            with open(history_file, "r") as hf:
                                lines = hf.readlines()
                            new_lines = [line for line in lines if session_id not in line]
                            with open(history_file, "w") as hf:
                                hf.writelines(new_lines)
                        except:
                            pass
    log_message(f"[{label}] Wakeup action completed.")

def get_latest_session_mtime(codex_dir):
    sessions_dir = os.path.join(codex_dir, "sessions")
    if not os.path.exists(sessions_dir):
        return 0
    latest_time = 0
    for root, dirs, files in os.walk(sessions_dir):
        for f in files:
            if f.endswith(".jsonl"):
                try:
                    mtime = os.path.getmtime(os.path.join(root, f))
                    if mtime > latest_time:
                        latest_time = mtime
                except:
                    pass
    return latest_time

def find_source_account(accounts):
    latest_time = 0
    source_acc = None
    for env_name, env_val, codex_dir, cmd_name, label in accounts:
        history_file = os.path.join(codex_dir, "history.jsonl")
        history_mtime = 0
        if os.path.exists(history_file):
            try:
                history_mtime = os.path.getmtime(history_file)
            except:
                pass
        session_mtime = get_latest_session_mtime(codex_dir)
        mtime = max(history_mtime, session_mtime)
        if mtime > latest_time:
            latest_time = mtime
            source_acc = (env_name, env_val, codex_dir, cmd_name, label)
    return source_acc

def migrate_latest_session(source_codex_dir, target_codex_dir):
    history_file = os.path.join(source_codex_dir, "history.jsonl")
    if not os.path.exists(history_file):
        print("No history file found in source account. Skipping session migration.")
        return None
        
    with open(history_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if not lines:
        print("History file is empty. Skipping session migration.")
        return None
        
    last_line = lines[-1].strip()
    try:
        session_data = json.loads(last_line)
        session_id = session_data.get("session_id")
    except Exception as e:
        print(f"Failed to parse latest history entry: {e}. Skipping migration.")
        return None
        
    if not session_id:
        print("No session_id found in the latest history entry. Skipping migration.")
        return None
        
    source_session_path = None
    sessions_dir = os.path.join(source_codex_dir, "sessions")
    for root, dirs, files in os.walk(sessions_dir):
        for f in files:
            if f.endswith(f"{session_id}.jsonl"):
                source_session_path = os.path.join(root, f)
                break
        if source_session_path:
            break
            
    if not source_session_path:
        print(f"Could not find session file for session {session_id} in source sessions directory.")
        return None
        
    rel_path = os.path.relpath(source_session_path, sessions_dir)
    target_session_path = os.path.join(target_codex_dir, "sessions", rel_path)
    os.makedirs(os.path.dirname(target_session_path), exist_ok=True)
    
    shutil.copy2(source_session_path, target_session_path)
    
    target_history_file = os.path.join(target_codex_dir, "history.jsonl")
    with open(target_history_file, "a", encoding="utf-8") as f:
        f.write(last_line + "\n")
        
    try:
        os.remove(source_session_path)
    except Exception as de:
        print(f"Warning: failed to delete source session file: {de}")
        
    try:
        with open(history_file, "w", encoding="utf-8") as f:
            f.writelines(lines[:-1])
    except Exception as he:
        print(f"Warning: failed to remove session entry from source history.jsonl: {he}")
        
    print(f"Successfully migrated session {session_id} to target.")
    return session_id

def main():
    check_log_size()
    config = load_config()
    
    is_switch_mode = "--switch" in sys.argv or "-s" in sys.argv
    is_interactive = sys.stdout.isatty() and "--silent" not in sys.argv
    
    accounts = discover_accounts(config)
    
    source_acc = None
    if is_switch_mode:
        print("================== Codex Account Auto-Switch and Migration Tool ==================")
        source_acc = find_source_account(accounts)
        if not source_acc:
            print("Error: Could not identify the source account directory based on file modifications.")
            sys.exit(1)
        source_env_name, source_env_val, source_codex_dir, source_cmd_name, source_label = source_acc
        print(f"Detected Source Account: {source_label} ({source_env_val})")
        print("Querying all accounts' quota status in parallel, please wait...")
    else:
        if is_interactive:
            print(f"\n================== Querying Codex Account Limits in Parallel ==================")
            print("Setting up secure channels and syncing status commands, please wait...")
        else:
            log_message("================== Starting Codex Keepalive Logic ==================")
            log_message(f"Dynamically discovered {len(accounts)} Codex account configuration(s).")
            
    # Query accounts in parallel
    subprocess.run("tmux start-server 2>/dev/null", shell=True)
    
    threads = []
    for i, (env_name, env_val, codex_dir, cmd_name, label) in enumerate(accounts):
        t = threading.Thread(target=fetch_account_metrics_thread, args=(env_name, env_val, codex_dir, cmd_name, label, config, i))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    # Compile status cache
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"
    GRAY = "\033[90m"
    
    def make_colored_bar(percent_val, width=20):
        if percent_val < 30:
            color = RED
        elif percent_val < 75:
            color = YELLOW
        else:
            color = GREEN
        filled = int(round(percent_val / 100.0 * width))
        empty = width - filled
        return f"{color}[{'█' * filled}{'░' * empty}]{RESET}"
        
    cache_lines = []
    cache_lines.append(f"{GRAY}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    cache_lines.append(f" {BOLD}{CYAN}⚙️  Codex Account Quota Snapshot{RESET} {GRAY}(Updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}){RESET}")
    cache_lines.append(f"{GRAY}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    
    for env_name, env_val, codex_dir, cmd_name, label in accounts:
        res = results.get(label)
        if not res or res["email"] == "unknown" or res["email"] == "未知" or not res["metrics"]:
            cache_lines.append(f" {BOLD}● {label}{RESET}  {RED}[FAILED OR NOT LOGGED IN]{RESET}")
            cache_lines.append(f"   {RED}⚠️  Please run '{cmd_name}' manually to log in again.{RESET}\n")
            continue
            
        email = res["email"]
        metrics = res["metrics"]
        cache_lines.append(f" {BOLD}● {label}{RESET}  {GRAY}[{email}]{RESET}")
        
        for name, info in metrics.items():
            limit = info["limit"]
            reset = info["reset"]
            percent_val = 100
            try:
                percent_val = int(limit.split("%")[0].strip())
            except:
                pass
            bar = make_colored_bar(percent_val, width=20)
            name_padded = name.ljust(12)
            
            limit_color = GREEN
            if percent_val < 30:
                limit_color = RED
            elif percent_val < 75:
                limit_color = YELLOW
            cache_lines.append(f"   {name_padded} {bar} {limit_color}{limit}{RESET} {GRAY}(resets: {reset}){RESET}")
        cache_lines.append("")
        
    cache_lines.append(f"{GRAY}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    
    # Always write cache if configured
    cache_file = os.path.join(STATE_DIR, "status_cache")
    if config.get("enable_terminal_snapshot", "true").lower() == "true":
        try:
            with open(cache_file, "w") as f:
                f.write("\n".join(cache_lines) + "\n")
            if not is_switch_mode and not is_interactive:
                log_message(f"Updated quota status cache to {cache_file}")
        except Exception:
            pass
            
    # Print table if interactive status query
    if is_interactive and not is_switch_mode:
        print("\n" + "\n".join(cache_lines) + "\n")
        
    # Execute specific branch
    if is_switch_mode and source_acc:
        candidates = [acc for acc in accounts if acc[2] != source_codex_dir]
        if not candidates:
            print("Error: No other accounts discovered to switch to. Verify ~/.bashrc configurations.")
            sys.exit(1)
            
        print("\nCandidates Evaluation:")
        best_candidate = None
        highest_score = -1.0
        
        for env_name, env_val, codex_dir, cmd_name, label in candidates:
            res = results.get(label)
            if not res or res["email"] == "unknown" or not res["metrics"]:
                print(f" ● {label}: Failed to fetch status (may be logged out). Skipping.")
                continue
                
            metrics = res["metrics"]
            info_5h = metrics.get("5h limit")
            info_weekly = metrics.get("Weekly limit")
            
            p_5h = 100
            t_5h = 5.0
            p_weekly = 100
            t_weekly = 168.0
            
            if info_5h:
                try:
                    p_5h = int(info_5h["limit"].split("%")[0].strip())
                except:
                    pass
                t_5h = parse_reset_time_to_hours(info_5h["reset"], is_weekly=False)
                
            if info_weekly:
                try:
                    p_weekly = int(info_weekly["limit"].split("%")[0].strip())
                except:
                    pass
                t_weekly = parse_reset_time_to_hours(info_weekly["reset"], is_weekly=True)
                
            score_5h = p_5h / t_5h
            score_weekly = (p_weekly * 7) / t_weekly
            score = min(score_5h, score_weekly)
            
            print(f" ● {label}: 5h limit: {p_5h}% (resets in {t_5h:.2f}h), Weekly limit: {p_weekly}% (resets in {t_weekly:.2f}h) -> Score: {score:.2f}")
            
            if score > highest_score:
                highest_score = score
                best_candidate = (env_name, env_val, codex_dir, cmd_name, label)
                
        if not best_candidate:
            print("\nError: No valid active candidates available.")
            sys.exit(1)
            
        target_env_name, target_env_val, target_codex_dir, target_cmd_name, target_label = best_candidate
        print(f"\nSelected Target Account: {target_label} with Score {highest_score:.2f}")
        
        print("\nMigrating latest session...")
        migrate_latest_session(source_codex_dir, target_codex_dir)
        
        print(f"\nLaunching {target_cmd_name} with migrated session...")
        new_env = os.environ.copy()
        new_env[target_env_name] = target_env_val
        sys.stdout.flush()
        sys.stderr.flush()
        try:
            os.execvpe("codex", ["codex", "resume", "--last", "--dangerously-bypass-approvals-and-sandbox"], new_env)
        except Exception as e:
            print(f"Error launching codex: {e}")
            sys.exit(1)
            
    else:
        # Keepalive Mode
        warnings = []
        for env_name, env_val, codex_dir, cmd_name, label in accounts:
            res = results.get(label)
            if not res or res["email"] == "unknown" or res["email"] == "未知" or not res["metrics"]:
                email = res["email"] if res else "unknown"
                log_message(f"[{label}] Not logged in or failed to fetch status!")
                warnings.append(f"  - {label} ({email}) Logged out! Run '{cmd_name}' manually to log in again.")
                continue
                
            email = res["email"]
            metrics = res["metrics"]
            log_message(f"[{label}] Email: {email}")
            
            weekly_info = metrics.get("Weekly limit")
            need_wakeup = False
            reason = ""
            
            if not weekly_info:
                other_limit_0_used = False
                for limit_name, limit_info in metrics.items():
                    try:
                        val = 100 - int(limit_info["limit"].split("%")[0])
                        if val == 0:
                            other_limit_0_used = True
                            break
                    except:
                        pass
                if other_limit_0_used or not metrics:
                    need_wakeup = True
                    reason = "No Weekly limit and other limits usage is 0% (or metrics empty), keepalive needed to activate new cycle"
                else:
                    need_wakeup = False
                    reason = "No Weekly limit but other limits show usage, new cycle running but metrics not shown"
            else:
                reset_str = weekly_info["reset"]
                limit_val = weekly_info["limit"]
                try:
                    used_percent = 100 - int(limit_val.split("%")[0])
                except:
                    used_percent = 0
                reset_dt = parse_reset_time_to_datetime(reset_str)
                now = datetime.datetime.now()
                
                if not reset_dt:
                    if used_percent == 0:
                        need_wakeup = True
                        reason = "Weekly limit usage is 0% and no clear reset time"
                    else:
                        need_wakeup = False
                        reason = f"Weekly limit has used {used_percent}%, countdown likely running but shown as unknown"
                else:
                    delta = reset_dt - now
                    if delta >= datetime.timedelta(days=7) - datetime.timedelta(minutes=10):
                        need_wakeup = True
                        reason = f"Reset time ({reset_str}) is {delta} from now (approx 7 days), keepalive needed to activate cycle"
                    else:
                        need_wakeup = False
                        reason = f"Current cycle locked and running (resets: {reset_str}, delta: {delta}, used: {used_percent}%)"
                        
            if need_wakeup:
                log_message(f"[{label}] {reason} -> Triggering keepalive wakeup")
                trigger_keepalive_exec(env_name, env_val, codex_dir, label, config)
                time.sleep(3)
            else:
                log_message(f"[{label}] {reason} -> Skipping wakeup")
                
        warning_file = os.path.join(STATE_DIR, "warning")
        if warnings and config.get("enable_login_warning", "true").lower() == "true":
            try:
                with open(warning_file, "w") as f:
                    f.write("\n".join(warnings) + "\n")
                log_message(f"Logged out account detected. Warning written to {warning_file}")
            except Exception:
                pass
        else:
            if os.path.exists(warning_file):
                try:
                    os.remove(warning_file)
                    log_message("All accounts healthy. Cleaned warning file.")
                except Exception:
                    pass
                    
        state_file = os.path.join(STATE_DIR, "keepalive.state")
        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(state_file, "w") as f:
                f.write(now_str)
            log_message(f"Updated keepalive execution timestamp to: {now_str}")
        except Exception:
            pass
            
        log_message("================== Keepalive Logic Execution Finished ==================\n")

if __name__ == "__main__":
    main()
