#!/usr/bin/env python3
import subprocess
import time
import re
import os
import sys
import threading
from datetime import datetime

USER_HOME = os.path.expanduser("~")
results = {}
lock = threading.Lock()

def discover_accounts():
    accounts = [
        ("HOME", USER_HOME, os.path.join(USER_HOME, ".codex"), "codex", "Primary Account (codex)")
    ]
    bashrc_path = os.path.join(USER_HOME, ".bashrc")
    if os.path.exists(bashrc_path):
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

def fetch_single_account_thread(env_name, env_val, codex_dir, cmd_name, label, index):
    # Stagger thread starts slightly by 0.5s to prevent concurrent tmux server race condition
    time.sleep(0.5 * index)
    
    clean_label = re.sub(r'[^a-zA-Z0-9_]', '', label.replace(' ', '_'))
    session_name = f"parallel_test_{clean_label}"
    
    subprocess.run(f"tmux kill-session -t {session_name} 2>/dev/null", shell=True)
    subprocess.run(f"tmux new-session -d -s {session_name} bash", shell=True)
    time.sleep(1)
    
    nvm_cmd = 'export NVM_DIR="/home/lzn/.nvm" && [ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"'
    run_cmd = f"{env_name}={env_val} codex"
    
    subprocess.run(f"tmux send-keys -t {session_name} '{nvm_cmd}' C-m", shell=True)
    time.sleep(0.5)
    subprocess.run(f"tmux send-keys -t {session_name} '{run_cmd}' C-m", shell=True)
    
    # 1. Dynamically wait for Codex to be ready instead of sleep(5)
    ready = False
    for _ in range(20):  # Wait up to 10 seconds (0.5s * 20)
        time.sleep(0.5)
        res = subprocess.run(f"tmux capture-pane -t {session_name} -p", shell=True, stdout=subprocess.PIPE, text=True)
        if "Collaboration mode:" in res.stdout or "Session:" in res.stdout or "›" in res.stdout:
            ready = True
            break
            
    # 2. Send the first /status to trigger background refresh request
    subprocess.run(f"tmux send-keys -t {session_name} '/status' C-m", shell=True)
    
    # 3. Wait 6 seconds for the client to complete sync with OpenAI in the background
    time.sleep(6)
    
    # 4. Clear prompt line and send second /status for capturing fresh metrics
    subprocess.run(f"tmux send-keys -t {session_name} C-u", shell=True)
    time.sleep(0.5)
    subprocess.run(f"tmux send-keys -t {session_name} '/status' C-m", shell=True)
    time.sleep(1)
    
    res = subprocess.run(f"tmux capture-pane -t {session_name} -p", shell=True, stdout=subprocess.PIPE, text=True)
    screen = res.stdout
    
    # 5. Kill session immediately
    subprocess.run(f"tmux kill-session -t {session_name} 2>/dev/null", shell=True)
    
    email = "unknown"
    metrics = {}
    
    email_match = re.search(r'Account:\s+([^\s(]+)', screen)
    if email_match:
        email = email_match.group(1).strip()
        
    for metric_name in ["5h limit", "Weekly limit", "Usage limit"]:
        limit, reset = parse_metric(metric_name, screen)
        if limit:
            metrics[metric_name] = {"limit": limit, "reset": reset}
            
    with lock:
        results[label] = {
            "email": email,
            "metrics": metrics
        }

def main():
    accounts = discover_accounts()
    print(f"Discovered {len(accounts)} accounts. Starting parallel query test...")
    
    start_time = time.time()
    
    threads = []
    for i, (env_name, env_val, codex_dir, cmd_name, label) in enumerate(accounts):
        t = threading.Thread(target=fetch_single_account_thread, args=(env_name, env_val, codex_dir, cmd_name, label, i))
        threads.append(t)
        t.start()
        
    print(f"All {len(threads)} threads spawned. Waiting for join...")
    
    for t in threads:
        t.join()
        
    end_time = time.time()
    total_duration = end_time - start_time
    
    print("\n================== PARALLEL TEST RESULTS ==================")
    print(f"Total time elapsed: {total_duration:.2f} seconds (Expected ~11s)\n")
    
    for env_name, env_val, codex_dir, cmd_name, label in accounts:
        res = results.get(label)
        if not res:
            print(f" ● {label}: FAILED TO RETRIEVE RESULT")
            continue
        email = res["email"]
        metrics = res["metrics"]
        print(f" ● {label} [{email}]:")
        if not metrics:
            print("   (No metrics found - possibly logged out)")
        for name, info in metrics.items():
            print(f"   - {name}: {info['limit']} (resets: {info['reset']})")
    print("===========================================================")

if __name__ == "__main__":
    main()
