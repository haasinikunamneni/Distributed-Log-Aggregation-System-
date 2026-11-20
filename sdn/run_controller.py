"""Launcher for the controller. os-ken's `osken-manager` script is missing on this platform, so we
start the same machinery directly.   Usage (from project root):  python3 -m sdn.run_controller"""
from os_ken.lib import hub
hub.patch(thread=True)
import sys
from os_ken import cfg, log
from os_ken.base.app_manager import AppManager
from os_ken.controller import controller  # noqa: registers --ofp-tcp-listen-port etc.


def main():
    cfg.CONF(args=[], project="os_ken", version="1.0")
    log.init_log()
    mgr = AppManager.get_instance()
    mgr.load_apps(["sdn.controller"])
    services = mgr.instantiate_apps(**mgr.create_contexts())
    try:
        hub.joinall(services)
    except KeyboardInterrupt:
        pass
    finally:
        mgr.close()


if __name__ == "__main__":
    main()
