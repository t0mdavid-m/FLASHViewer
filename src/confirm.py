"""src/confirm.py — the two confirmation patterns.

Four actions delete something today with no confirmation at all:
  Delete Workspace   shutil.rmtree(path)          unbounded, unrecoverable
  Remove all         FileManager.clear_cache()    unbounded, unrecoverable  x3 pages
  Remove selected    remove_results(id) per id    bounded, named
  Remove one         same                         bounded, named

Unbounded gets a typed confirmation. Bounded gets a dialog listing the ids.

Note on colour: Streamlit has no danger button type. type="primary" is navy for
every button in the app, and redColor reaches badges and markdown, not fills.
The weight is carried by the wording, the count in the label, and the icon. Do
not fake it with a coloured emoji.
"""
import streamlit as st

_ICON = ":material/delete_forever:"


@st.dialog("Confirm")
def confirm_typed(title, body, phrase, confirm_label, on_confirm):
    """Typed confirmation. For Remove all.

    NOT for Delete Workspace: that lives inside @st.dialog("Settings · Workspace")
    already, Streamlit permits one dialog at a time, and nesting raises. Use
    confirm_typed_inline for it.
    """
    _typed_body(title, body, phrase, confirm_label, on_confirm, key=f"confirm_{phrase}")


def confirm_typed_inline(title, body, phrase, confirm_label, on_confirm, key):
    """The same pattern rendered in place, for use inside an existing dialog.

    The typed field and the disabled button appear under the button that armed
    them.
    """
    _typed_body(title, body, phrase, confirm_label, on_confirm, key=key)


def _typed_body(title, body, phrase, confirm_label, on_confirm, key):
    st.markdown(f"**{title}**")
    st.write(body)
    typed = st.text_input(f"Type {phrase} to confirm", key=key)
    # Compared exactly: no case folding, no trimming beyond surrounding
    # whitespace, and against a phrase the dialog itself displays so it can be
    # copied. The button enables only once the field commits (Enter or blur) —
    # st.text_input does not rerun per keystroke. Expected, not a bug.
    armed = typed.strip() == phrase
    c1, c2 = st.columns(2)
    if c1.button("Cancel", key=f"{key}_cancel", use_container_width=True):
        st.rerun()
    if c2.button(confirm_label, key=f"{key}_go", disabled=not armed,
                 icon=_ICON, use_container_width=True,
                 help=None if armed else f"Type {phrase} above to enable this.",
                 type="primary"):
        on_confirm()


@st.dialog("Confirm")
def confirm_list(ids, on_confirm, body, cap=8):
    """Dialog listing what goes. For Remove selected and Remove one."""
    n = len(ids)
    if n == 1:
        st.markdown(f"**Remove {_truncate(ids[0], 40)}**")
    else:
        st.markdown(f"**Remove {n} datasets**")

    shown = ids[:cap]
    st.code("\n".join(shown), language=None)
    if n > cap:
        st.caption(f"and {n - cap} more")

    st.write(body)

    # Cancel first, left, secondary. The destructive button never holds focus
    # on open, and the confirm label repeats the action and the count — never
    # "OK", "Yes", "Confirm", or a bare "Delete".
    c1, c2 = st.columns(2)
    if c1.button("Cancel", use_container_width=True):
        st.rerun()
    label = "Remove 1 dataset" if n == 1 else f"Remove {n} datasets"
    if c2.button(label, type="primary", icon=_ICON, use_container_width=True):
        on_confirm()


def _truncate(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + "\u2026"


# ------------------------------------------------- Delete Workspace, for common.py

DELETE_WORKSPACE_BODY = (
    "Deletes the directory {path} and everything in it: parameters, all three "
    "tool caches, and every dataset. This cannot be undone."
)
