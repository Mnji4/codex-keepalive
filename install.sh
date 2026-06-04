#!/usr/bin/env bash

# Codex Keepalive & Monitor Installer
# This script configures executable permissions and registers terminal hooks in your shell profiles (~/.bashrc and ~/.zshrc).

# Exit immediately if a command exits with a non-zero status
set -e

# Resolve directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/codex-keepalive"

echo "Initializing installation..."

# Make scripts executable
chmod +x "$SCRIPT_DIR/codex_keepalive.py"
chmod +x "$SCRIPT_DIR/codex_keepalive.sh"

# If current directory is not the target installation folder, copy all repository files
if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
    echo "Creating installation directory at: $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    cp "$SCRIPT_DIR/codex_keepalive.py" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/codex_keepalive.sh" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/config.toml" "$INSTALL_DIR/"
fi

# Detect shell config files (.bashrc and .zshrc)
SHELL_FILES=()
[ -f "$HOME/.bashrc" ] && SHELL_FILES+=("$HOME/.bashrc")
[ -f "$HOME/.zshrc" ] && SHELL_FILES+=("$HOME/.zshrc")

# If none exists, default to .bashrc
if [ ${#SHELL_FILES[@]} -eq 0 ]; then
    SHELL_FILES+=("$HOME/.bashrc")
fi

# Inject aliases and terminal opening hooks
for CONF in "${SHELL_FILES[@]}"; do
    echo "Registering alias and hooks in $CONF..."
    
    # 1. Clean up legacy background triggers to prevent terminal launch bloating
    if [ -f "$CONF" ]; then
        # Remove any line that triggers the keepalive wrapper script
        sed -i '/codex_keepalive.sh/d' "$CONF"
    fi

    # 2. Inject codex_status alias
    if ! grep -q "alias codex_status=" "$CONF"; then
        echo 'alias codex_status="python3 ~/codex-keepalive/codex_keepalive.py"' >> "$CONF"
    fi
    
    # 3. Inject non-blocking startup hooks (ONLY display cache, NO background trigger)
    if ! grep -q "Codex Quota Status Snapshot Display" "$CONF"; then
        cat << 'EOF' >> "$CONF"

# Codex Connection Alert (Logged Out Warning)
if [ -f "$HOME/codex-keepalive/state/warning" ]; then
    echo -e "\n\033[91m\033[1m⚠️  [Codex Connection Warning] The following accounts require manual login:\033[0m"
    cat "$HOME/codex-keepalive/state/warning"
    echo -e "\033[93mHint: Please run the corresponding command (e.g., codex, codex0...) manually to log in and re-bind.\033[0m\n"
fi

# Codex Quota Status Snapshot Display
if [ -f "$HOME/codex-keepalive/state/status_cache" ]; then
    cat "$HOME/codex-keepalive/state/status_cache"
fi
EOF
        echo "Successfully configured hooks in $CONF"
    else
        echo "Hooks already present in $CONF, skipping hooks setup."
    fi
done

# Setup or update crontab entry for background checks (triggered every 3 hours)
echo "Configuring crontab entry for checking every 3 hours..."
CRON_JOB="0 */3 * * * /bin/bash $INSTALL_DIR/codex_keepalive.sh"

# Read current crontab
crontab -l 2>/dev/null > tmp_cron || true

# Remove any existing codex_keepalive.sh references to prevent duplicates and clean old paths
sed -i '/codex_keepalive.sh/d' tmp_cron

# Append new 3-hour cron job
echo "$CRON_JOB" >> tmp_cron

# Apply updated crontab
crontab tmp_cron
rm tmp_cron
echo "Crontab successfully updated to run every 3 hours."

echo -e "\n\033[92m✔ Installation complete!\033[0m"
echo "--------------------------------------------------------"
echo "1. Run: source <your_shell_profile> (e.g., source ~/.zshrc or source ~/.bashrc)"
echo "2. Run: codex_status at any time to query live updates."
echo "3. Customize triggers & snapshot display inside config.toml."
echo "--------------------------------------------------------"
