"""Label -> profile-field mapping. The browser half needs a real page, but a wrong
mapping here silently types a surname into a phone box."""

from cli.apply import group_radios, is_consent, match_field, to_spec


def test_maps_common_english_and_polish_labels():
    assert match_field("First Name *") == "first_name"
    assert match_field("Nazwisko") == "last_name"
    assert match_field("E-mail address") == "email"
    assert match_field("Telefon kontaktowy") == "phone"
    assert match_field("LinkedIn Profile URL") == "linkedin"
    assert match_field("Oczekiwane wynagrodzenie") == "salary"


def test_specific_label_beats_the_generic_one():
    # "first name" contains "name"; the longer fragment has to win, or every name
    # field collapses onto full_name
    assert match_field("first name") == "first_name"
    assert match_field("Your full name") == "full_name"
    # "e-mail" must not be read as the "mail" of some unrelated field
    assert match_field("Work e-mail") == "email"


def test_unknown_and_empty_labels_map_to_nothing():
    # these are exactly the ones that now go to the LLM pass instead
    assert match_field("How did you hear about us?") is None
    assert match_field("") is None
    assert match_field("   ") is None


def _radio(index: int, name: str, label: str) -> dict:
    return {
        "index": index, "tag": "input", "type": "radio", "name": name, "label": label,
        "options": [], "required": True, "maxLength": None,
    }


def test_radios_sharing_a_name_become_one_question_with_options():
    controls = group_radios([_radio(3, "work_permit", "Yes"), _radio(4, "work_permit", "No")])
    assert len(controls) == 1
    assert controls[0]["options"] == ["Yes", "No"]
    # applying an answer has to reach the right radio, not the group's first one
    assert controls[0]["members"] == {"Yes": 3, "No": 4}


def test_nameless_radios_stay_separate():
    assert len(group_radios([_radio(1, "", "Yes"), _radio(2, "", "No")])) == 2


def test_non_radio_controls_pass_through_untouched():
    text = {**_radio(0, "", "Email"), "type": "email"}
    assert group_radios([text]) == [text]


def test_spec_carries_the_options_a_dropdown_must_be_answered_from():
    spec = to_spec({
        "index": 7, "tag": "select", "type": "text", "name": "seniority", "label": "Seniority",
        "options": ["Junior", "Mid", "Senior"], "required": True, "maxLength": None,
    })
    assert (spec.kind, spec.options, spec.required) == ("select", ["Junior", "Mid", "Senior"], True)


def test_consent_labels_are_recognised_in_both_languages():
    assert is_consent("I agree to the privacy policy")
    assert is_consent("Wyrażam zgodę na przetwarzanie danych (RODO)")
    assert not is_consent("Years of React experience")
