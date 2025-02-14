import os, sys, platform, shutil, sysconfig
import argparse
import scribe_data

def main():

    # Check if the current platform is Linux
    if platform.system() != "Linux":
        print("This package is only supported on Linux systems.", file=sys.stderr)
        sys.exit(0)

    parser = argparse.ArgumentParser("Install the desktop file for the scribe package. Any arguments to this script will be passed on to `scribe`.")
    o, rest = parser.parse_known_args()
    o.arguments = rest

    SOURCE_SCRIBE_DATA = os.path.dirname(scribe_data.__file__)

    HOME = os.environ.get('HOME',os.path.expanduser('~'))
    XDG_SHARE = os.environ.get('XDG_DATA_HOME', os.path.join(HOME, '.local','share'))
    XDG_APP_DATA = os.path.join(XDG_SHARE, 'applications')

    # Create the directory if it doesn't exist
    os.makedirs(XDG_APP_DATA, exist_ok=True)

    with open(os.path.join(SOURCE_SCRIBE_DATA, 'templates', 'scribe.desktop')) as f:
        template = f.read()

    bin_folder = sysconfig.get_path("scripts")
    icon_folder = os.path.join(SOURCE_SCRIBE_DATA, 'share')
    desktop_filecontent = template.format(icon_folder=icon_folder, bin_folder=bin_folder, options=' '.join(o.arguments) if o.arguments else '')

    desktop_filepath = os.path.join(XDG_APP_DATA, 'scribe.desktop')
    print("Writing GNOME desktop file:", desktop_filepath)
    with open(desktop_filepath, "w") as f:
        f.write(desktop_filecontent)


if __name__ == "__main__":
    main()