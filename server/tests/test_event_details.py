import pytest
from pydantic import ValidationError
from src.models.session_data import Payload


def event(**extra):
    return Payload(timestamp='2026-10-09T12:00:00Z', element_type='input',
                   element_name='answer', action_type='interactions',
                   event_type='change', element_html='<input>', **extra)


def test_legacy_event_without_details_remains_valid():
    assert event().details is None


@pytest.mark.parametrize('details', [
    {'checked': False},
    {'selected_indices': [0, 2], 'option_count': 3},
    {'keyboard_action': 'typing'},
    {'keyboard_action': 'editing'},
])
def test_new_event_details_survive_serialization(details):
    actual = event(details=details).model_dump()['details']
    for name, value in details.items():
        assert actual[name] == value


def test_keyboard_details_reject_arbitrary_key_contents():
    with pytest.raises(ValidationError):
        event(details={'keyboard_action': 'secret-text'})
