"""Native file-picker helpers for scribe.

Kept scribe-local for now so the worktree is self-contained; promotion to
``desktop_ai_core.frontends.dialog`` is a follow-up once the API settles.
"""

from __future__ import annotations


def select_file_save(
    title: str = "Choose output file",
    initial_dir: str | None = None,
    initial_file: str = "scribe-transcript.txt",
) -> str | None:
    """Open a native 'Save As' file dialog. Returns the chosen path or None
    if the user cancelled. Uses tkinter from stdlib (no extra dependency).

    The hidden ``Tk()`` root is withdrawn before the dialog and destroyed in
    a ``finally`` so we don't leak a zombie top-level window when called
    repeatedly from the tray menu.
    """
    import os
    from tkinter import Tk, filedialog, messagebox

    root = Tk()
    root.withdraw()
    try:
        path = filedialog.asksaveasfilename(
            title=title,
            initialdir=initial_dir,
            initialfile=initial_file,
            defaultextension=".txt",
            # "All files" first so existing files of any extension are
            # visible by default — the picker is for "where to dump the
            # transcript", not "type a new .txt name".
            filetypes=[("All files", "*.*"), ("Text", "*.txt")],
            # We APPEND to the file, never overwrite, so tk's default
            # "Replace?" prompt would be misleading. Suppress it and
            # ask a more accurate "Append to existing?" below.
            confirmoverwrite=False,
        )
        if not path:
            return None
        # When the user picked an existing file, confirm the intent —
        # the recording will *append*, never overwrite.
        if os.path.exists(path):
            basename = os.path.basename(path)
            keep = messagebox.askyesno(
                "Append to existing file?",
                f"'{basename}' already exists. New chunks will be appended to it. Continue?",
            )
            if not keep:
                return None
        return path
    finally:
        root.destroy()
