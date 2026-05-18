#!/usr/bin/env bash
set -e

PLUGIN_ID="${1:-}"

if [ -z "$PLUGIN_ID" ]; then
  echo "Usage: curl -fsSL https://cdn.jsdelivr.net/npm/@kiran_nandi_123/conxa/scripts/install.sh | bash -s -- <plugin-id>"
  exit 1
fi

if ! command -v node &>/dev/null; then
  echo "[conxa] Node.js not found — installing..."
  if [[ "$OSTYPE" == "darwin"* ]]; then
    if command -v brew &>/dev/null; then
      brew install node
    else
      NODE_VER="20.18.0"
      echo "[conxa] Downloading Node.js ${NODE_VER}..."
      curl -fsSL "https://nodejs.org/dist/v${NODE_VER}/node-v${NODE_VER}.pkg" -o /tmp/_conxa_node.pkg
      sudo installer -pkg /tmp/_conxa_node.pkg -target /
      rm -f /tmp/_conxa_node.pkg
    fi
  elif command -v apt-get &>/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
    sudo apt-get install -y nodejs
  elif command -v yum &>/dev/null; then
    curl -fsSL https://rpm.nodesource.com/setup_lts.x | sudo bash -
    sudo yum install -y nodejs
  else
    NODE_VER="20.18.0"
    ARCH=$(uname -m)
    [[ "$ARCH" == "x86_64" ]] && ARCH="x64"
    [[ "$ARCH" == "aarch64" ]] && ARCH="arm64"
    echo "[conxa] Downloading Node.js binary..."
    curl -fsSL "https://nodejs.org/dist/v${NODE_VER}/node-v${NODE_VER}-linux-${ARCH}.tar.xz" \
      | sudo tar -xJ -C /usr/local --strip-components=1
  fi
fi

npx -y @kiran_nandi_123/conxa install "$PLUGIN_ID"
