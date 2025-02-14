import os, sys, platform, shutil, sysconfig
import argparse

def main():

    # Check if the current platform is Linux
    if platform.system() != "Linux":
        print("This package is only supported on Linux systems.", file=sys.stderr)
        sys.exit(0)

    parser = argparse.ArgumentParser("Install the desktop file for the scribe package. Any arguments to this script will be passed on to `scribe`.")
    o, rest = parser.parse_known_args()
    o.arguments = rest

    PACKAGE_NAME = 'scribe'

    HOME = os.environ.get('HOME',os.path.expanduser('~'))
    XDG_SHARE = os.environ.get('XDG_DATA_HOME', os.path.join(HOME, '.local','share'))
    XDG_APP_DATA = os.path.join(XDG_SHARE, 'applications')
    XDG_SCRIBE_DATA = os.path.join(XDG_SHARE, PACKAGE_NAME)


    # Create the directory if it doesn't exist
    os.makedirs(XDG_SCRIBE_DATA, exist_ok=True)
    os.makedirs(XDG_APP_DATA, exist_ok=True)

    # Copy your files to the desired location
    print("Copying files to", XDG_SCRIBE_DATA)
    shutil.copy('share/icon.jpg', XDG_SCRIBE_DATA)

    with open('templates/scribe.desktop') as f:
        template = f.read()

    bin_folder = sysconfig.get_path("scripts")
    desktop_file = template.format(XDG_SCRIBE_DATA=XDG_SCRIBE_DATA, bin_folder=bin_folder, options=' '.join(o.arguments))

    print("Writing desktop file to", XDG_APP_DATA)
    with open(os.path.join(XDG_APP_DATA, 'scribe.desktop'), "w") as f:
        f.write(desktop_file)


if __name__ == "__main__":
    main()