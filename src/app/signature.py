# -*- coding: utf-8 -*-
"""Terminal startup signature for the InterRats Tracker application."""

from __future__ import annotations

import os
import shutil
import sys


GREEN = "\033[38;2;0;255;136m"
RESET = "\033[0m"
FULL_SIGNATURE_MIN_WIDTH = 80

LOGO = r"""
██╗███╗   ██╗████████╗███████╗██████╗ ██████╗  █████╗ ████████╗
██║████╗  ██║╚══██╔══╝██╔════╝██╔══██╗██╔══██╗██╔══██╗╚══██╔══╝
██║██╔██╗ ██║   ██║   █████╗  ██████╔╝██████╔╝███████║   ██║
██║██║╚██╗██║   ██║   ██╔══╝  ██╔══██╗██╔══██╗██╔══██║   ██║
██║██║ ╚████║   ██║   ███████╗██║  ██║██║  ██║██║  ██║   ██║
╚═╝╚═╝  ╚═══╝   ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝
"""

ASCII_LOGO = r"""
  ___       __           ____        __
 |_ _|_ __ / /____ _ __ |  _ \ __ _ / /____
  | || '_ \| __/ _ \ '__|| |_) / _` | __/ __|
  | || | | | ||  __/ |   |  _ < (_| | |_\__ \
 |___|_| |_|\__\___|_|   |_| \_\__,_|\__|___/
"""

RAT_ART = r"""
                                                                       .  :
- +. +
- @ ==%*#.
                                                 **%#+*.         .*#+=::-=+#+%
                                              .%======%:#.:#%+---============+.
                                              %=======+#=-==+#% .%======+==+=%.
                                             :@%%#===*::====# @@@-====+=*===*%
                                          .#-::=*+:+#*:======# . *====+=+==@*-
                                          #::#=:::::@=================@=#%=++
                             .++++++++++++*-*=::::::::+##=========%===@=+##: ==
                        =@-:::::::::::::::#=#+=::::::-%===============++*@:
                    :*=:--========+#==+#==*+=#+=====+%=*#============+*%:  =-
                  +*:::-=====@=============+%========*+==========++***@ =
                 :*::-====*##=================*####****===========+****+*#    -
               -*:-=========+=======================*%++=======+****%
              *:-=#*====================================**=#===+***%-
            .*:===%+===========================================*+**-
           .*:--=*+======================****+===========+====+***%
           %%=-=====+%*====#%+++++++++****#+****===========*====***#
           :*===============-:=#********+##+*+============#+**+*#+
           *================**::*#-*++*+++**+++=============***+*
          #================%#%:=**+++++++**@%#+=============***%.
          *=================*+=:+***********##*+==========+*#+*:
         =***%=============+====-#***********#+*+========**%=%#
         @**%**===========*#@===:#*********++*%**+====+*#%**=*
        .%*+%**+============+===:#******+******+*#+*==%-*#***=%
        #++*%***+==============#%#+*+#*#@*%#+**@#%#@===:*.%**+=*
     .%:+%***@****+===========%*+***%******#@***#*%*+===# :%+*******+%
   :#:*#=*#**+%******++*+++*%***+**###+=+######****@*++=+=. =#**#%+*+%
  #-::=+*     :%@@%%#@**%@+#@@@@=.                  #+**+==%%*@. :%:
 #****==        .#+*****++++======+***=             -#*+*+++###:
-:::-=%          %**************+=##*=%*#-             .#%**.-#:
*:=+++#               =+*##*+***%**+=#*+%-
#::::-%                      .:%%%. .:+ .     =%%#=#--------*-*%#
*=::::-*                            :-=**:+::::----@=======%=======-%-
.%=-+-::-%=                  *%#-#-:::::--=#==*%%-:..          .-%%====#
  +%==-:::#:::::-*--:::::-::::::-#===+****:                         #====*
    .=%==-+:::::--::::::======+%%-.                               .%*===*
          =***++*+++++***+.                                  :#+=====++*
"""

INFO = """
:: InterRats Tracker ::
:: Initialization sequence started ::
:: Signature loaded ::
:: Status: INITIALIZING ::
:: Access: AUTHORIZED ::
"""

COMPACT_SIGNATURE = """
==============================
      InterRats Tracker
     Status: INITIALIZING
==============================
"""


def supports_color() -> bool:
    """Return whether ANSI color should be emitted to the current output."""
    if os.getenv("NO_COLOR") is not None:
        return False
    if os.getenv("TERM") == "dumb":
        return False

    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def show_signature() -> None:
    """Display the visual startup signature for InterRats Tracker."""
    terminal_width = shutil.get_terminal_size(fallback=(120, 30)).columns
    content = COMPACT_SIGNATURE if terminal_width < FULL_SIGNATURE_MIN_WIDTH else _full_signature()
    if not _can_output_unicode(content):
        content = COMPACT_SIGNATURE if terminal_width < FULL_SIGNATURE_MIN_WIDTH else _full_signature(ascii_safe=True)

    if supports_color():
        _enable_windows_ansi()
        _write_output(f"{GREEN}{content}{RESET}\n")
    else:
        _write_output(f"{content}\n")

    sys.stdout.flush()


def _full_signature(ascii_safe: bool = False) -> str:
    logo = ASCII_LOGO if ascii_safe else LOGO
    return f"{logo}\n{RAT_ART}\n{INFO}"


def _enable_windows_ansi() -> None:
    if os.name == "nt":
        os.system("")


def _can_output_unicode(content: str) -> bool:
    if _is_windows_tty():
        return True

    encoding = sys.stdout.encoding or sys.getdefaultencoding()
    try:
        content.encode(encoding)
    except UnicodeEncodeError:
        return False
    return True


def _write_output(content: str) -> None:
    try:
        sys.stdout.write(content)
    except UnicodeEncodeError:
        if _write_windows_console(content):
            return

        encoding = sys.stdout.encoding or sys.getdefaultencoding()
        safe_content = content.encode(encoding, errors="replace").decode(encoding, errors="replace")
        sys.stdout.write(safe_content)


def _is_windows_tty() -> bool:
    return os.name == "nt" and hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _write_windows_console(content: str) -> bool:
    if not _is_windows_tty():
        return False

    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetStdHandle(-11)
        written = ctypes.c_ulong()
        return bool(ctypes.windll.kernel32.WriteConsoleW(handle, content, len(content), ctypes.byref(written), None))
    except Exception:
        return False
