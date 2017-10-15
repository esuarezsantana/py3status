# -*- coding: utf-8 -*-
"""
Show an indicator when YubiKey is waiting for a touch.

Configuration parameters:
    format: Display format for the module.
        (default '\?if=is_waiting YubiKey')
    gpg_check_timeout: Time to wait for gpg check response.
        Use value as small as possible that doesn't introduce false positives.
        (default 0.1)
    gpg_check_watch_paths: A list of files to watch, start gpg check if any one was opened.
        (default ['~/.gnupg/pubring.kbx', '~/.ssh/known_hosts'])
    sudo_check_watch_paths: A list of files to watch, start sudo check if any one was opened.
        (default ['~/.config/Yubico/u2f_keys'])

Control placeholders:
    {is_waiting} a boolean indicating whether YubiKey is waiting for a touch.

SAMPLE OUTPUT
{'color': '#00FF00', 'full_text': 'YubiKey'}

Dependencies:
    gpg: to check for pending gpg access request
    inotify-simple: to check for pending gpg and sudo requests
    subprocess32: if after all these years you are still using python2

@author Maxim Baz (https://github.com/maximbaz)
@license BSD
"""

import time
import os
import signal
import sys
import threading
import inotify_simple

if os.name == 'posix' and sys.version_info[0] < 3:
    import subprocess32 as subprocess
else:
    import subprocess


class Py3status:
    """
    """
    # available configuration parameters
    format = '\?if=is_waiting YubiKey'
    gpg_check_timeout = 0.1
    gpg_check_watch_paths = ['~/.gnupg/pubring.kbx', '~/.ssh/known_hosts']
    sudo_check_watch_paths = ['~/.config/Yubico/u2f_keys']

    def post_config_hook(self):
        self.gpg_check_watch_paths = [
            os.path.expanduser(p) for p in self.gpg_check_watch_paths
        ]
        self.sudo_check_watch_paths = [
            os.path.expanduser(p) for p in self.sudo_check_watch_paths
        ]

        self.killed = threading.Event()

        self.pending_gpg = False
        self.pending_sudo = False

        class GpgThread(threading.Thread):
            def _check_card_status(this):
                return subprocess.Popen(
                    'gpg --no-tty --card-status',
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=os.setsid)

            def _set_pending(this, new_value):
                self.pending_gpg = new_value
                if not self.pending_sudo:
                    self.py3.update()

            def run(this):
                inotify = inotify_simple.INotify()
                watches = []
                for path in self.gpg_check_watch_paths:
                    if os.path.isfile(path):
                        watch = inotify.add_watch(path,
                                                  inotify_simple.flags.OPEN)
                        watches.append(watch)

                while not self.killed.is_set():
                    for event in inotify.read():
                        # e.g. ssh doesn't start immediately, try several seconds to be sure
                        for i in range(20):
                            with this._check_card_status() as check:
                                try:
                                    # if this doesn't return very quickly, touch is pending
                                    check.communicate(
                                        timeout=self.gpg_check_timeout)
                                    time.sleep(0.25)
                                except subprocess.TimeoutExpired:
                                    this._set_pending(True)
                                    os.killpg(check.pid, signal.SIGINT)
                                    check.communicate()
                                    # wait until device is touched
                                    with this._check_card_status() as wait:
                                        wait.communicate()
                                        this._set_pending(False)
                                        break

                        # ignore all events caused by operations above
                        for _ in inotify.read():
                            pass

                for watch in watches:
                    inotify.rm_watch(watch)

        class SudoThread(threading.Thread):
            def _restart_sudo_reset_timer(this):
                if this.sudo_reset_timer is not None:
                    this.sudo_reset_timer.cancel()

                this.sudo_reset_timer = threading.Timer(
                    5, lambda: this._set_pending(False))
                this.sudo_reset_timer.start()

            def _set_pending(this, new_value):
                self.pending_sudo = new_value
                if not self.pending_gpg:
                    self.py3.update()

            def run(this):
                this.sudo_reset_timer = None

                inotify = inotify_simple.INotify()
                watches = []
                for path in self.sudo_check_watch_paths:
                    if os.path.isfile(path):
                        watch = inotify.add_watch(path,
                                                  inotify_simple.flags.OPEN)
                        watches.append(watch)

                while not self.killed.is_set():
                    for event in inotify.read():
                        this._restart_sudo_reset_timer()
                        this._set_pending(True)

                for watch in watches:
                    inotify.rm_watch(watch)

        if len(self.gpg_check_watch_paths) > 0:
            GpgThread().start()

        if len(self.sudo_check_watch_paths) > 0:
            SudoThread().start()

    def yubikey(self):
        is_waiting = self.pending_gpg or self.pending_sudo
        format_params = {'is_waiting': is_waiting}
        response = {
            'cached_until': self.py3.CACHE_FOREVER,
            'full_text': self.py3.safe_format(self.format, format_params),
        }
        if is_waiting:
            response['urgent'] = True
        return response

    def kill(self):
        self.killed.set()


if __name__ == "__main__":
    """
    Run module in test mode.
    """
    from py3status.module_test import module_test
    module_test(Py3status)
