"""Reply parsing checks only; no remote service is contacted."""
from types import SimpleNamespace
from science_agent_backend.pod_terminal import PodTerminal


def screen(*lines):
    return SimpleNamespace(display=list(lines), columns=160,
                           history=SimpleNamespace(top=[]))


def test_reply_requires_current_begin_marker():
    assert PodTerminal._answer(screen('Old answer', '\u2570\u2500'), 'begin', 'end') is None


def test_reply_without_end_marker_can_use_closed_panel():
    assert PodTerminal._answer(screen('begin', 'Verified upload; submission failed.', '\u2570\u2500'),
                               'begin', 'end') == 'Verified upload; submission failed.'


def test_partial_reply_is_not_complete():
    assert PodTerminal._answer(screen('begin', 'Still running'), 'begin', 'end') is None


def test_explicit_end_marker():
    assert PodTerminal._answer(screen('begin', 'Done', 'end'), 'begin', 'end') == 'Done'
