#!/usr/bin/env bash
PLIST_NAME="com.techno.newsagent"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

if [ -f "$PLIST_PATH" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo "🛑 Techno News Agent service stopped and removed."
else
    echo "Service is not installed."
fi

