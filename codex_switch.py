#!/usr/bin/env python3
import os
import sys
import re
import time
import datetime
import subprocess
import threading
import shutil
import json

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

def fetch_single_account_thread(env_name, env_val, codex_dir, cmd_name, label, config, index):
    time.sleep(1.0 * index)
    clean_label = re.sub(r'[^a-zA-Z0-9_]', '', label.replace(' ', '_'))
    session_name = f"switch_status_check_{clean_label}"
    
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
            "env_name": env_name,
            "env_val": env_val,
            "codex_dir": codex_dir,
            "email": email,
            "metrics": metrics
        }

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
    config = load_config()
    accounts = discover_accounts(config)
    
    print("================== Codex Account Auto-Switch and Migration Tool ==================")
    
    # 1. Detect source account
    source_acc = find_source_account(accounts)
    if not source_acc:
        print("Error: Could not identify the source account directory based on file modifications.")
        sys.exit(1)
        
    source_env_name, source_env_val, source_codex_dir, source_cmd_name, source_label = source_acc
    print(f"Detected Source Account: {source_label} ({source_env_val})")
    
    # Candidates are remaining accounts
    candidates = [acc for acc in accounts if acc[2] != source_codex_dir]
    if not candidates:
        print("Error: No other accounts discovered to switch to. Please verify ~/.bashrc configuration.")
        sys.exit(1)
        
    # 2. Query candidates' quota status in parallel
    print("Querying other accounts' quota status in parallel, please wait...")
    subprocess.run("tmux start-server 2>/dev/null", shell=True)
    
    threads = []
    for i, (env_name, env_val, codex_dir, cmd_name, label) in enumerate(candidates):
        t = threading.Thread(target=fetch_single_account_thread, args=(env_name, env_val, codex_dir, cmd_name, label, config, i))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
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
        
        # Default to full quota if not present
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
            
        # Score formula: min(5h_limit_percent / T_5h, (Weekly_limit_percent * 7) / T_weekly)
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
    
    # 3. Migrate session files
    print("\nMigrating latest session...")
    session_id = migrate_latest_session(source_codex_dir, target_codex_dir)
    
    # 4. Launch new client
    print(f"\nLaunching {target_cmd_name} with migrated session...")
    new_env = os.environ.copy()
    new_env[target_env_name] = target_env_val
    
    # Replace current process with codex
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        os.execvpe("codex", ["codex", "resume", "--last", "--dangerously-bypass-approvals-and-sandbox"], new_env)
    except Exception as e:
        print(f"Error launching codex: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
