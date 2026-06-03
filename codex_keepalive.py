#!/usr/bin/env python3
import subprocess
import time
import re
import datetime
import os
import sys
import json

# Define state and log paths dynamically based on user home
USER_HOME = os.path.expanduser("~")
LOG_FILE = os.path.join(USER_HOME, ".codex_keepalive.log")

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
        "keepalive_interval_hours": "24",
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

def load_state():
    state_file = os.path.join(USER_HOME, ".codex_keepalive.state")
    default_state = {
        "last_run": "1970-01-01 00:00:00",
        "next_resets": {}
    }
    if not os.path.exists(state_file):
        return default_state
    try:
        with open(state_file, "r") as f:
            content = f.read().strip()
        # Fallback compatibility with legacy plain text timestamps
        if not content.startswith("{"):
            if len(content) == 10:
                content += " 00:00:00"
            default_state["last_run"] = content
            return default_state
        return json.loads(content)
    except Exception:
        return default_state

def save_state(last_run_str, next_resets):
    state_file = os.path.join(USER_HOME, ".codex_keepalive.state")
    state = {
        "last_run": last_run_str,
        "next_resets": next_resets
    }
    try:
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass

def check_should_run(config):
    if config.get("enable_daily_keepalive", "true").lower() != "true":
        return False
        
    state = load_state()
    now = datetime.datetime.now()
    
    # 1. Smart Scheduler: Check if any account has passed its next scheduled weekly reset time
    any_reset_expired = False
    for label, reset_time_str in state.get("next_resets", {}).items():
        if not reset_time_str:
            continue
        try:
            reset_dt = datetime.datetime.strptime(reset_time_str, "%Y-%m-%d %H:%M:%S")
            if now >= reset_dt:
                any_reset_expired = True
                log_message(f"[Scheduler] Account '{label}' has passed its scheduled weekly reset time ({reset_time_str}). Forcing a wakeup run.")
                break
        except Exception:
            pass
            
    if any_reset_expired:
        return True
        
    # 2. Fallback: Revert to normal interval check
    try:
        last_run = datetime.datetime.strptime(state.get("last_run", "1970-01-01 00:00:00"), "%Y-%m-%d %H:%M:%S")
        interval_hours = int(config.get("keepalive_interval_hours", "24"))
        
        if now - last_run < datetime.timedelta(hours=interval_hours):
            return False
    except Exception:
        pass
    return True

def cleanup_files(config):
    if config.get("enable_terminal_snapshot", "true").lower() != "true":
        cache_file = os.path.join(USER_HOME, ".codex_status_cache")
        if os.path.exists(cache_file):
            try:
                os.remove(cache_file)
            except Exception:
                pass
                
    if config.get("enable_login_warning", "true").lower() != "true":
        warning_file = os.path.join(USER_HOME, ".codex_warning")
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

def fetch_account_metrics(home_dir, label, config):
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
    time.sleep(5)
    
    subprocess.run(f"tmux send-keys -t {session_name} '/status' C-m", shell=True)
    time.sleep(5)
    
    email = "unknown"
    metrics = {}
    
    for attempt in range(5):
        subprocess.run(f"tmux send-keys -t {session_name} C-u", shell=True)
        time.sleep(0.5)
        subprocess.run(f"tmux send-keys -t {session_name} '/status' C-m", shell=True)
        time.sleep(4)
        
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
        time.sleep(1)
        
    subprocess.run(f"tmux kill-session -t {session_name} 2>/dev/null", shell=True)
    return email, metrics

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
    
    for _ in range(10):
        time.sleep(1)
        res = subprocess.run(f"tmux capture-pane -t {session_name} -p", shell=True, stdout=subprocess.PIPE, text=True)
        if "model:" in res.stdout or "Tip:" in res.stdout:
            break
            
    subprocess.run(f"tmux send-keys -t {session_name} '/resume' C-m", shell=True)
    
    for _ in range(10):
        time.sleep(1)
        res = subprocess.run(f"tmux capture-pane -t {session_name} -p", shell=True, stdout=subprocess.PIPE, text=True)
        if "enter resume" in res.stdout or "Sort:" in res.stdout:
            break
            
    chat_name = config.get("keepalive_chat_name", "keepalive")
    subprocess.run(f"tmux send-keys -t {session_name} '{chat_name}'", shell=True)
    time.sleep(2)
    
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
        time.sleep(10)
    else:
        log_message(f"[{label}] Successfully found chat '{chat_name}', entering to edit historical message...")
        subprocess.run(f"tmux send-keys -t {session_name} C-m", shell=True)
        
        for _ in range(10):
            time.sleep(1)
            res = subprocess.run(f"tmux capture-pane -t {session_name} -p", shell=True, stdout=subprocess.PIPE, text=True)
            if "enter resume" not in res.stdout and "›" in res.stdout:
                break
                
        subprocess.run(f"tmux send-keys -t {session_name} Escape", shell=True)
        time.sleep(0.5)
        subprocess.run(f"tmux send-keys -t {session_name} Up", shell=True)
        time.sleep(0.5)
        subprocess.run(f"tmux send-keys -t {session_name} C-m", shell=True)
        time.sleep(0.5)
        
        subprocess.run(f"tmux send-keys -t {session_name} C-u", shell=True)
        new_msg = "keepalive at " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subprocess.run(f"tmux send-keys -t {session_name} '{new_msg}' C-m", shell=True)
        time.sleep(10)
        
    subprocess.run(f"tmux kill-session -t {session_name} 2>/dev/null", shell=True)
    log_message(f"[{label}] Wakeup action completed.")

def main():
    check_log_size()
    config = load_config()
    
    if not check_should_run(config):
        cleanup_files(config)
        sys.exit(0)
        
    log_message("================== Starting Codex Keepalive Logic (TUI History Edit Version) ==================")
    accounts = discover_accounts(config)
    log_message(f"Dynamically discovered {len(accounts)} Codex account configuration(s).")
    
    subprocess.run("tmux start-server 2>/dev/null", shell=True)
    
    warnings = []
    results = {}
    
    for home_dir, cmd_name, label in accounts:
        log_message(f"[{label}] Checking quota status... (HOME={home_dir})")
        email, metrics = fetch_account_metrics(home_dir, label, config)
        
        results[label] = {
            "email": email,
            "metrics": metrics
        }
        
        if not metrics or email == "unknown" or email == "未知":
            log_message(f"[{label}] Not logged in or failed to fetch status!")
            warnings.append(f"  - {label} ({email}) Logged out! Run '{cmd_name}' manually to log in again.")
            continue
            
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
            trigger_keepalive_tui(home_dir, label, config)
            time.sleep(3)
        else:
            log_message(f"[{label}] {reason} -> Skipping wakeup")
            
    warning_file = os.path.join(USER_HOME, ".codex_warning")
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
                
    cache_file = os.path.join(USER_HOME, ".codex_status_cache")
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
                
    # Record next resets and update state
    next_resets = {}
    for home_dir, cmd_name, label in accounts:
        res = results.get(label)
        if not res or not res["metrics"]:
            continue
        weekly_info = res["metrics"].get("Weekly limit")
        if weekly_info:
            reset_str = weekly_info["reset"]
            reset_dt = parse_reset_time_to_datetime(reset_str)
            if reset_dt:
                next_resets[label] = reset_dt.strftime("%Y-%m-%d %H:%M:%S")

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_state(now_str, next_resets)
    log_message(f"Updated keepalive execution timestamp to: {now_str}")
    log_message("================== Keepalive Logic Execution Finished ==================\n")

if __name__ == "__main__":
    main()
