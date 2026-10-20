#!/usr/bin/env bash
# Run only in a disposable Fedora container; no host home directories are mounted.
set -eu
dnf install -y /packages/*.rpm xorg-x11-server-Xvfb xorg-x11-xauth dbus-x11 shadow-utils
useradd --create-home smoke
install -d -o smoke -g smoke /home/smoke/.code-ai
printf 'check_system_proxy: false\n' > /home/smoke/.code-ai/desktop.yaml
chown smoke:smoke /home/smoke/.code-ai/desktop.yaml
# Docker does not provide WebKit's user-namespace sandbox. This exception is
# confined to the test process; it is never part of the shipped launcher.
runuser -u smoke -- env WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1 \
  xvfb-run -a dbus-run-session -- timeout 120 \
  /opt/claude-china/claude-china-desktop --smoke-test /tmp/rpm-smoke.json
grep -q '"ok": true' /tmp/rpm-smoke.json
grep -q '"frozen": true' /tmp/rpm-smoke.json
dnf remove -y claude-china-desktop
if rpm -q claude-china-desktop; then
  echo 'The package is still registered after removal' >&2
  exit 1
fi
test ! -e /opt/claude-china/claude-china-desktop
test ! -L /usr/bin/claude-china-desktop
test ! -e /usr/share/applications/claude-china.desktop
test ! -e /usr/share/icons/hicolor/256x256/apps/claude-china.png
test "$(cat /home/smoke/.code-ai/desktop.yaml)" = 'check_system_proxy: false'
cat /tmp/rpm-smoke.json
echo 'RPM installation, native GUI and package removal passed; user settings preserved.'
