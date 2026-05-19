"""This module handles typing characters as if they were typed on a keyboard."""
import time
import unidecode


def type_text(text, interval=0, paste=False, ascii=False):
    from scribe.typers import pick_typer
    typer = pick_typer()

    if ascii:
        text = unidecode.unidecode(text)

    if paste:
        import pyperclip
        keep_state = pyperclip.paste()
        pyperclip.copy(text)
        typer.paste()
        pyperclip.copy(keep_state)
        return

    if interval > 0:
        for c in text:
            typer.type(c)
            time.sleep(interval)
    else:
        typer.type(text)
