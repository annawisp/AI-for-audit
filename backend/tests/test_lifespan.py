import asyncio
import logging

import app.main as main_module


def test_normal_shutdown_emits_application_stopped_log(caplog, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(main_module, "configure_logging", lambda _: None)

    async def run_lifespan() -> None:
        async with main_module.app.router.lifespan_context(main_module.app):
            pass

    with caplog.at_level(logging.INFO):
        asyncio.run(run_lifespan())

    messages = [record.getMessage() for record in caplog.records]
    assert "application_started" in messages
    assert "application_stopped" in messages
