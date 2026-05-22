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
    from tkinter import Tk, filedialog

    root = Tk()
    root.withdraw()
    try:
        path = filedialog.asksaveasfilename(
            title=title,
            initialdir=initial_dir,
            initialfile=initial_file,
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")],
        )
        return path or None
    finally:
        root.destroy()
