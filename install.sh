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
chmod +x "$SCRIPT_DIR/codex_status.py"

# If current directory is not the target installation folder, copy all repository files
if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
    echo "Creating installation directory at: $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    cp "$SCRIPT_DIR/codex_keepalive.py" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/codex_keepalive.sh" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/codex_status.py" "$INSTALL_DIR/"
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
    
    # Inject codex_status alias
    if ! grep -q "alias codex_status=" "$CONF"; then
        echo 'alias codex_status="python3 ~/codex-keepalive/codex_status.py"' >> "$CONF"
    fi
    
    # Inject non-blocking startup hooks
    if ! grep -q "Codex Auto Keepalive Trigger" "$CONF"; then
        cat << 'EOF' >> "$CONF"

# Codex Auto Keepalive Trigger (Silent Asynchronous)
# This script runs silently in the background and checks config.toml's keepalive_interval_hours to determine whether to trigger keepalive.
nohup bash "$HOME/codex-keepalive/codex_keepalive.sh" >/dev/null 2>&1 &

# Codex Connection Alert (Logged Out Warning)
if [ -f "$HOME/.codex_warning" ]; then
    echo -e "\n\033[91m\033[1m⚠️  [Codex Connection Warning] The following accounts require manual login:\033[0m"
    cat "$HOME/.codex_warning"
    echo -e "\033[93mHint: Please run the corresponding command (e.g., codex, codex0...) manually to log in and re-bind.\033[0m\n"
fi

# Codex Quota Status Snapshot Display
if [ -f "$HOME/.codex_status_cache" ]; then
    cat "$HOME/.codex_status_cache"
fi
EOF
        echo "Successfully configured hooks in $CONF"
    else
        echo "Hooks already present in $CONF, skipping hooks setup."
    fi
done

echo -e "\n\033[92m✔ Installation complete!\033[0m"
echo "--------------------------------------------------------"
echo "1. Run: source <your_shell_profile> (e.g., source ~/.zshrc or source ~/.bashrc)"
echo "2. Run: codex_status at any time to query live updates."
echo "3. Customize triggers & snapshot display inside config.toml."
echo "--------------------------------------------------------"
