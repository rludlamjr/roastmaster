"""Smoke tests to verify all modules import correctly."""


def test_import_roastmaster():
    import roastmaster

    assert roastmaster.__version__ == "0.1.0"


def test_import_app():
    from roastmaster import app

    assert hasattr(app, "main")


def test_import_config():
    from roastmaster import config

    assert config.SCREEN_WIDTH == 640
    assert config.SCREEN_HEIGHT == 480


def test_import_submodules():
    from roastmaster import display, engine, hal, profiles, serial, sim

    assert display is not None
    assert engine is not None
    assert hal is not None
    assert profiles is not None
    assert serial is not None
    assert sim is not None


def test_import_theme():
    from roastmaster.display import theme

    assert theme.GREEN_BRIGHT == (51, 255, 51)
