#!/usr/bin/env bash
# Ubuntu 24.04 only. Run from the project folder:  bash scripts/setup_ubuntu.sh
set -e
sudo apt update
sudo apt install -y python3-pip python3-venv mininet openvswitch-switch iperf iputils-ping ethtool unzip
sudo systemctl enable --now openvswitch-switch || true
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt
echo "Setup finished. Next: source .venv/bin/activate && python -m pytest -q tests"
