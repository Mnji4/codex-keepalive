#!/usr/bin/env python3
import subprocess
import time
import re
import os
import sys
import threading
from datetime import datetime

# ANSI color codes for pretty output
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"
GRAY = "\033[90m"

USER_HOME = os.path.expanduser("~")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(SCRIPT_DIR, "state")
os.makedirs(STATE_DIR, exist_ok=True)
results = {}
lock = threading.Lock()

def load_config():
    config = {
        "nvm_dir": os.path.join(USER_HOME, ".nvm"),
        "discover_aliases": "true"
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

def fetch_single_account_thread(home_dir, cmd_name, label, config, index):
    # Stagger thread starts slightly by 1.0s to prevent concurrent tmux server race condition
    time.sleep(1.0 * index)
    
    clean_label = re.sub(r'[^a-zA-Z0-9_]', '', label.replace(' ', '_'))
    session_name = f"cpa_status_check_{clean_label}"
    
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
            "cmd": cmd_name,
            "home": home_dir,
            "email": email,
            "metrics": metrics,
            "raw": screen
        }

    try:
        clean_file_label = re.sub(r'[^a-zA-Z0-9_]', '', label.replace(' ', '_'))
        screen_file = os.path.join(STATE_DIR, f"screen_{clean_file_label}.txt")
        with open(screen_file, "w") as f:
            f.write(screen)
    except Exception:
        pass

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

def main():
    config = load_config()
    accounts = discover_accounts(config)
    print(f"\n{BOLD}{CYAN}================== Querying Codex Account Limits in Parallel =================={RESET}")
    print("Setting up secure channels and syncing status commands, please wait...")
    
    subprocess.run("tmux start-server 2>/dev/null", shell=True)
    
    threads = []
    for i, (home_dir, cmd_name, label) in enumerate(accounts):
        t = threading.Thread(target=fetch_single_account_thread, args=(home_dir, cmd_name, label, config, i))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    print(f"\n{GRAY}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    print(f" {BOLD}{CYAN}⚙️  Codex Account Real-Time Quota Status{RESET} {GRAY}(Query Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}){RESET}")
    print(f"{GRAY}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    
    for _, _, label in accounts:
        res = results.get(label)
        if not res or res["email"] == "unknown" or res["email"] == "未知" or not res["metrics"]:
            cmd_name = res["cmd"] if res else "codex"
            print(f" {BOLD}● {label}{RESET}  {RED}[FAILED OR NOT LOGGED IN]{RESET}")
            print(f"   {RED}⚠️  Please run '{cmd_name}' manually to log in again.{RESET}\n")
            continue
            
        email = res["email"]
        metrics = res["metrics"]
        print(f" {BOLD}● {label}{RESET}  {GRAY}[{email}]{RESET}")
        
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
                
            print(f"   {name_padded} {bar} {limit_color}{limit}{RESET} {GRAY}(resets: {reset}){RESET}")
        print()
        
    print(f"{GRAY}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}\n")

if __name__ == "__main__":
    main()
