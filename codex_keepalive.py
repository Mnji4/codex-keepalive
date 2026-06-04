#!/usr/bin/env python3
import subprocess
import time
import re
import datetime
import os
import sys
import threading
import random

# Define state and log paths dynamically based on script location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(SCRIPT_DIR, "state")
os.makedirs(STATE_DIR, exist_ok=True)

USER_HOME = os.path.expanduser("~")
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
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.toml")
    
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
        (USER_HOME, "codex", "Primary Account (codex)")
    ]
    
    if config.get("discover_aliases", "true").lower() != "true":
        return accounts
        
    bashrc_path = os.path.join(USER_HOME, ".bashrc")
    if not os.path.exists(bashrc_path):
        return accounts
        
    try:
        with open(bashrc_path, "r") as f:
            content = f.read()
            
        pattern = re.compile(r'alias\s+([a-zA-Z0-9_-]+)\s*=\s*["\']HOME=([^\s"\']+) codex["\']')
        matches = pattern.findall(content)
        
        seen_homes = {USER_HOME}
        for cmd_name, home_path in matches:
            full_home = os.path.realpath(os.path.expanduser(home_path))
            if full_home not in seen_homes:
                seen_homes.add(full_home)
                accounts.append((full_home, cmd_name, f"Alias Account ({cmd_name})"))
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

def fetch_account_metrics_thread(home_dir, label, config, index):
    # Stagger thread starts slightly by 1.0s to prevent concurrent tmux server race condition
    time.sleep(1.0 * index)
    
    clean_label = re.sub(r'[^a-zA-Z0-9_]', '', label.replace(' ', '_'))
    session_name = f"keepalive_check_{clean_label}"
    
    subprocess.run(f"tmux kill-session -t {session_name} 2>/dev/null", shell=True)
    subprocess.run(f"tmux new-session -d -s {session_name} bash", shell=True)
    time.sleep(1)
    
    nvm_dir = config.get("nvm_dir", os.path.join(USER_HOME, ".nvm"))
    nvm_cmd = f'export NVM_DIR="{nvm_dir}" && [ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"'
    run_cmd = f"HOME={home_dir} codex"

    subprocess.run(f"tmux send-keys -t {session_name} '{nvm_cmd}' C-m", shell=True)
    time.sleep(0.5)
    subprocess.run(f"tmux send-keys -t {session_name} '{run_cmd}' C-m", shell=True)
    
    # 1. Dynamically wait for Codex to be ready instead of sleep(5)
    ready = False
    for _ in range(60):  # Wait up to 30 seconds (0.5s * 60)
        time.sleep(0.5)
        res = subprocess.run(f"tmux capture-pane -t {session_name} -p", shell=True, stdout=subprocess.PIPE, text=True)
        if "Collaboration mode:" in res.stdout or "Session:" in res.stdout or ("›" in res.stdout and "Booting" not in res.stdout):
            ready = True
            break
            
    # 2. Send the first /status to trigger background refresh request
    subprocess.run(f"tmux send-keys -t {session_name} '/status' C-m", shell=True)
    
    # 3. Wait 6 seconds for the client to complete sync with OpenAI in the background
    time.sleep(6)
    
    email = "unknown"
    metrics = {}
    screen = ""
    
    # 4. Try sending /status and capturing, with retries if sync is not yet complete
    for attempt in range(4):
        if attempt > 0:
            time.sleep(3)  # Wait 3 seconds before retrying
            
        subprocess.run(f"tmux send-keys -t {session_name} C-u", shell=True)
        time.sleep(0.5)
        subprocess.run(f"tmux send-keys -t {session_name} '/status' C-m", shell=True)
        time.sleep(1.5)  # Give it 1.5s to render the TUI table
        
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
            
    # 5. Kill session immediately
    subprocess.run(f"tmux kill-session -t {session_name} 2>/dev/null", shell=True)
    
    with lock:
        results[label] = {
            "email": email,
            "metrics": metrics
        }

def get_random_prose():
    prose_list = [
        "在这个寂静的深夜，屏幕散发着微弱的幽蓝色光芒，一行行代码如同流星般在深邃的夜空中划过。指尖在键盘上轻快地跳跃，敲击声宛如一首无声的夜曲，打破了四周的喧嚣。每一个字符的输入，都是对逻辑与秩序 of 探索，每一个函数的调用，都在构建一个虚拟而美妙的微观世界。窗外夜色正浓，月光如流水般洒落在窗台上，与室内的灯光交相辉映。在这个由零和一构成的浩瀚宇宙中，思想如同脱缰的野马自由驰骋，跨越了物理的边界，去寻找解决难题的终极答案。这不仅是一次简单的保活测试，更是灵魂在数字荒野中的一次短途旅行，让代码的律动伴随着深夜的静谧，流淌向未知的远方。",
        "晨曦微露，第一缕阳光穿透薄雾，轻轻拂过街道两旁林立的霓虹招牌。空气中弥漫着泥土与青草的芬芳，宣告着新一天的降临。远处的山峦在晨光中逐渐清晰，轮廓如同一幅淡雅的水墨画，层叠交错，绵延起伏。时间在这里仿佛放慢了脚步，溪流在山谷间缓缓流淌，发出清脆悦耳的叮咚声。在这个喧嚣世界的一隅，总有一处静谧的角落，让人能够暂时忘却日常的琐碎与忙碌，静静倾听大自然的心跳。让这篇关于清晨与远山的随笔，跨越数字信号的桥梁，化作一行行跳跃的字符，唤醒沉睡中的系统，在新的周期里继续记录时间无声流淌的痕迹。",
        "漂浮在半空中的城市，正缓缓穿过五彩斑斓的云层。反重力引擎发出低沉而有节奏的嗡嗡声，如同古老巨兽的低吟，在金属舱壁间回荡。窗外是无边无际 of 星海，璀璨的恒星群如同一颗颗碎钻洒在黑色的天鹅绒幕布上。这里的引力参数被精确调整，人们在街区之间轻盈地漂浮、滑翔，仿佛身处一场永无止境的太空华尔兹之中。科技的边缘与科幻的幻想在此处重合，人类的智慧将曾经的不可思议变成了脚下坚实的金属大地。这不仅是对重力的抗拒，更是人类对自由的不懈追求，在星际的洪流中，用坚定的步伐迈向未知的星系与明天的破晓。"
    ]
    # Append instruction and timestamp to ensure it's always unique and triggers redraw/rewrite
    instruction = " 请对以上这段文字作出一篇简短的随笔感悟（约一百字即可）。"
    timestamp = datetime.datetime.now().strftime(" (Keepalive at %Y-%m-%d %H:%M:%S)")
    return random.choice(prose_list) + instruction + timestamp

def trigger_keepalive_tui(home_dir, label, config):
    log_message(f"[{label}] Spawning keyboard macro to edit the last message in '{config.get('keepalive_chat_name', 'keepalive')}' to trigger activation...")
    clean_label = re.sub(r'[^a-zA-Z0-9_]', '', label.replace(' ', '_'))
    session_name = f"keepalive_trigger_{clean_label}"
    subprocess.run(f"tmux kill-session -t {session_name} 2>/dev/null", shell=True)
    subprocess.run(f"tmux new-session -d -s {session_name} bash", shell=True)
    time.sleep(1)
    
    nvm_dir = config.get("nvm_dir", os.path.join(USER_HOME, ".nvm"))
    nvm_cmd = f'export NVM_DIR="{nvm_dir}" && [ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"'
    run_cmd = f"HOME={home_dir} codex"

    subprocess.run(f"tmux send-keys -t {session_name} '{nvm_cmd}' C-m", shell=True)
    time.sleep(0.5)
    subprocess.run(f"tmux send-keys -t {session_name} '{run_cmd}' C-m", shell=True)
    
    # Wait for codex start
    for _ in range(10):
        time.sleep(1)
        res = subprocess.run(f"tmux capture-pane -t {session_name} -p", shell=True, stdout=subprocess.PIPE, text=True)
        if "model:" in res.stdout or "Tip:" in res.stdout:
            break
            
    # Enter /resume list
    subprocess.run(f"tmux send-keys -t {session_name} '/resume' C-m", shell=True)
    
    # Wait for list load
    for _ in range(10):
        time.sleep(1)
        res = subprocess.run(f"tmux capture-pane -t {session_name} -p", shell=True, stdout=subprocess.PIPE, text=True)
        if "enter resume" in res.stdout or "Sort:" in res.stdout:
            break
            
    # Search for keepalive
    chat_name = config.get("keepalive_chat_name", "keepalive")
    subprocess.run(f"tmux send-keys -t {session_name} '{chat_name}'", shell=True)
    time.sleep(2)
    
    # Check if found
    res = subprocess.run(f"tmux capture-pane -t {session_name} -p", shell=True, stdout=subprocess.PIPE, text=True)
    
    no_chat_indicators = ["No results", "0 / 0", "No saved chat", "No matches"]
    has_keepalive = True
    for indicator in no_chat_indicators:
        if indicator in res.stdout:
            has_keepalive = False
            break
            
    if not has_keepalive:
        log_message(f"[{label}] Chat room named '{chat_name}' not found. Auto sending message to create it.")
        subprocess.run(f"tmux send-keys -t {session_name} Escape", shell=True)
        time.sleep(1)
        subprocess.run(f"tmux send-keys -t {session_name} '{chat_name}' C-m", shell=True)
        time.sleep(15)
    else:
        log_message(f"[{label}] Successfully found chat '{chat_name}', entering to edit historical message...")
        subprocess.run(f"tmux send-keys -t {session_name} C-m", shell=True)
        
        # Wait for loading
        for _ in range(10):
            time.sleep(1)
            res = subprocess.run(f"tmux capture-pane -t {session_name} -p", shell=True, stdout=subprocess.PIPE, text=True)
            if "enter resume" not in res.stdout and "›" in res.stdout:
                break
                
        # Esc -> Up -> Enter to edit
        subprocess.run(f"tmux send-keys -t {session_name} Escape", shell=True)
        time.sleep(0.5)
        subprocess.run(f"tmux send-keys -t {session_name} Up", shell=True)
        time.sleep(0.5)
        subprocess.run(f"tmux send-keys -t {session_name} C-m", shell=True)
        time.sleep(0.5)
        
        # Clear and send modified message
        subprocess.run(f"tmux send-keys -t {session_name} C-u", shell=True)
        new_msg = get_random_prose()
        subprocess.run(["tmux", "set-buffer", "-b", "ka_buf", new_msg], check=True)
        subprocess.run(f"tmux paste-buffer -b ka_buf -t {session_name}", shell=True)
        subprocess.run(f"tmux send-keys -t {session_name} C-m", shell=True)
        time.sleep(25)
        
    try:
        res = subprocess.run(f"tmux capture-pane -t {session_name} -p", shell=True, stdout=subprocess.PIPE, text=True)
        screen_ka_file = os.path.join(STATE_DIR, f"screen_ka_{clean_label}.txt")
        with open(screen_ka_file, "w") as f:
            f.write(res.stdout)
    except Exception:
        pass

    subprocess.run(f"tmux kill-session -t {session_name} 2>/dev/null", shell=True)
    log_message(f"[{label}] Wakeup action completed.")

def main():
    check_log_size()
    config = load_config()
    
    # Check if keepalive is globally enabled
    if config.get("enable_daily_keepalive", "true").lower() != "true":
        cleanup_files(config)
        sys.exit(0)
        
    log_message("================== Starting Codex Keepalive Logic (TUI History Edit Version) ==================")
    accounts = discover_accounts(config)
    log_message(f"Dynamically discovered {len(accounts)} Codex account configuration(s).")
    
    # Ensure tmux server is running
    subprocess.run("tmux start-server 2>/dev/null", shell=True)
    
    # Concurrent parallel queries for all accounts
    threads = []
    for i, (home_dir, cmd_name, label) in enumerate(accounts):
        t = threading.Thread(target=fetch_account_metrics_thread, args=(home_dir, label, config, i))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    warnings = []
    
    for home_dir, cmd_name, label in accounts:
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
            # Check other limits for activity if Weekly limit is not currently rendered
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
                # If reset time is equal to or close to 7 days ahead (>= 7 days - 10 mins), it's not activated
                if delta >= datetime.timedelta(days=7) - datetime.timedelta(minutes=10):
                    need_wakeup = True
                    reason = f"Reset time ({reset_str}) is {delta} from now (approx 7 days), keepalive needed to activate cycle"
                else:
                    need_wakeup = False
                    reason = f"Current cycle locked and running (resets: {reset_str}, delta: {delta}, used: {used_percent}%)"
                    
        if need_wakeup:
            log_message(f"[{label}] {reason} -> Triggering keepalive wakeup")
            trigger_keepalive_tui(home_dir, label, config)
            time.sleep(3)
        else:
            log_message(f"[{label}] {reason} -> Skipping wakeup")
            
    # Write alert log
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
                
    # Update quota cache view
    cache_file = os.path.join(STATE_DIR, "status_cache")
    if config.get("enable_terminal_snapshot", "true").lower() == "true":
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
        
        for _, cmd_name, label in accounts:
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
        
        try:
            with open(cache_file, "w") as f:
                f.write("\n".join(cache_lines) + "\n")
            log_message(f"Updated quota status cache to {cache_file}")
        except Exception:
            pass
    else:
        if os.path.exists(cache_file):
            try:
                os.remove(cache_file)
            except Exception:
                pass
                
    # Record state execution timestamp
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
