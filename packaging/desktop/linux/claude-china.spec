Name: claude-china-desktop
Version: @VERSION@
Release: 1
Summary: Claude China desktop launcher
License: MIT
URL: https://github.com/invoker-bot/Claude-China
BuildArch: x86_64
Requires: glibc >= 2.35, gtk3, webkit2gtk4.1, libayatana-appindicator-gtk3
AutoReqProv: no

%description
Standalone launcher for configured AI desktop applications.
Python and the application are included. User settings are preserved on removal.

%install
mkdir -p "%{buildroot}"
cp -a "%{_sourcedir}/root/." "%{buildroot}/"

%files
/opt/claude-china
/usr/bin/claude-china-desktop
/usr/share/applications/claude-china.desktop
/usr/share/icons/hicolor/256x256/apps/claude-china.png
