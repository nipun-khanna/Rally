from scripts import place_vapi_call


def test_cli_dry_run_never_places_call(monkeypatch, capsys):
    class FakeDialer:
        def __init__(self, *args):
            pass
        def ready(self):
            return True
        def place_call(self, *, to_number):
            raise AssertionError("dry run dialed")

    monkeypatch.setattr(place_vapi_call, "VapiDialer", FakeDialer)
    monkeypatch.setattr(place_vapi_call, "load_vapi_settings",
                        lambda: ("key", "assistant", "number"))
    assert place_vapi_call.main([]) == 0
    assert "+16785991244" in capsys.readouterr().out


def test_cli_rejects_wrong_destination_before_network(monkeypatch, capsys):
    monkeypatch.setattr(place_vapi_call, "load_vapi_settings",
                        lambda: (_ for _ in ()).throw(AssertionError("loaded secrets")))
    assert place_vapi_call.main(["--place", "--number", "+17032004231"]) == 2
    assert "authorized" in capsys.readouterr().err


def test_cli_explicit_place_reports_provider_id(monkeypatch, capsys):
    calls = []
    class FakeDialer:
        def __init__(self, *args):
            pass
        def ready(self):
            return True
        def place_call(self, *, to_number):
            calls.append(to_number)
            return {"id": "019a9046-121e-766d-bd1f-84f3ccc309c1", "status": "queued"}
    monkeypatch.setattr(place_vapi_call, "VapiDialer", FakeDialer)
    monkeypatch.setattr(place_vapi_call, "load_vapi_settings",
                        lambda: ("key", "assistant", "number"))
    assert place_vapi_call.main(["--place"]) == 0
    assert calls == ["+16785991244"]
    assert "queued" in capsys.readouterr().out
