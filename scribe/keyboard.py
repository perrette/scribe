"""This module handles typing characters as if they were typed on a keyboard."""
import time
import unidecode


def type_text(text, interval=0, paste=False, ascii=False, typer="auto"):
    from scribe.typers import pick_typer
    _typer = pick_typer(typer if typer != "auto" else None)

    if ascii:
        text = unidecode.unidecode(text)

    if paste:
        import pyperclip
        keep_state = pyperclip.paste()
        pyperclip.copy(text)
        _typer.paste()
        pyperclip.copy(keep_state)
        return

    if interval > 0:
        for c in text:
            _typer.type(c)
            time.sleep(interval)
    else:
        _typer.type(text)
