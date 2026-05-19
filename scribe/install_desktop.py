import os, sys, platform, shutil, sysconfig
import argparse
import scribe_data

def main():

    # Check if the current platform is Linux
    if platform.system() != "Linux":
        print("This package is only supported on Linux systems.", file=sys.stderr)
        sys.exit(0)

    parser = argparse.ArgumentParser("Install the desktop file for the scribe package. Any arguments to this script will be passed on to `scribe`.")
    parser.add_argument("--name", help="The title of the desktop app", default="Scribe")
    parser.add_argument("--startup-wm-class")
    parser.add_argument("--frontend", choices=["tray", "terminal"], default="tray",
                        help="Frontend to launch (default: tray). 'terminal' opens a terminal window.")
    o, rest = parser.parse_known_args()
    o.arguments = rest

    terminal = (o.frontend == "terminal")
    if o.frontend == "terminal" and "--frontend" not in o.arguments:
        o.arguments.extend(["--frontend", "terminal"])

    SOURCE_SCRIBE_DATA = os.path.dirname(scribe_data.__file__)

    HOME = os.environ.get('HOME',os.path.expanduser('~'))
    XDG_SHARE = os.environ.get('XDG_DATA_HOME', os.path.join(HOME, '.local','share'))
    XDG_APP_DATA = os.path.join(XDG_SHARE, 'applications')

    # Create the directory if it doesn't exist
    os.makedirs(XDG_APP_DATA, exist_ok=True)

    with open(os.path.join(SOURCE_SCRIBE_DATA, 'templates', 'scribe.desktop')) as f:
        template = f.read()

    simple_name = o.name.lower().replace(' ','-').replace(os.path.sep, '-')
    bin_folder = sysconfig.get_path("scripts")
    icon_folder = os.path.join(SOURCE_SCRIBE_DATA, 'share')
    desktop_filecontent = template.format(icon_folder=icon_folder, bin_folder=bin_folder,
                                          name=o.name, terminal=str(terminal).lower(),
                                          StartupWMClass=o.startup_wm_class or f"crx_mpnasdanpmm_{simple_name}",
                                          options=' ' + ' '.join(o.arguments) if o.arguments else '')

    desktop_filepath = os.path.join(XDG_APP_DATA, f'{simple_name}.desktop')
    print("Writing GNOME desktop file:", desktop_filepath)
    with open(desktop_filepath, "w") as f:
        f.write(desktop_filecontent)

    _post_install_typer_hint()


def _post_install_typer_hint():
    """On Linux Wayland sessions without ``eitype`` installed, print
    instructions for getting native-Wayland-compatible keyboard injection.
    pynput's XTest backend (the only fallback) only reaches apps running
    under XWayland — native Wayland clients silently drop the events.
    """
    if platform.system() != "Linux":
        return
    is_wayland = bool(
        os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("XDG_SESSION_TYPE") == "wayland"
    )
    if not is_wayland:
        return
    if shutil.which("eitype") is not None:
        return

    print()
    print("─── Recommended: install eitype for native-Wayland keyboard input ───")
    print()
    print("You're on a Wayland session, so scribe's default typer backend")
    print("(pynput's XTest) will only reach apps running under XWayland.")
    print("Native-Wayland apps (Firefox with MOZ_ENABLE_WAYLAND=1, modern KDE")
    print("apps, GNOME Console, …) won't receive scribe's keystrokes.")
    print()
    print("For full coverage, install eitype (libei via XDG RemoteDesktop")
    print("portal — works on GNOME 45+, KDE Plasma 6.1+, Hyprland):")
    print()
    print("  # 1. Install rustup if you don't have it:")
    print("  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh")
    print("  source \"$HOME/.cargo/env\"")
    print()
    print("  # 2. Install eitype:")
    print("  cargo install --git https://github.com/Adam-D-Lewis/eitype")
    print()
    print("Scribe will auto-detect it on next launch.")
    print()


if __name__ == "__main__":
    main()