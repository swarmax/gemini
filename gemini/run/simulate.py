"""One run in one call: ``gm.simulate``, ``gm.replay``, ``gm.live`` and ``gm.resume``.

Each function builds an ``Engine``, calls the matching method and returns its ``Results``; the
run logic is the engine's, and the engine stays public for what one call cannot do: a run held in
memory, a callback that reads it, a manual checkpoint. No object is kept between calls. The plant
holds what the compiler traced, so a second call on one plant does not trace it again.
"""

from contextlib import contextmanager

from gemini.engine.callbacks import AutoCheckpoint
from gemini.engine.engine import Engine
from gemini.errors import RunError, ValidationError
from gemini.run._utils.apply import apply_case
from gemini.run.schedule import scheduled


def _with_autosave(callbacks, checkpoint, checkpoint_every):
    """Return ``callbacks`` and, for ``checkpoint_every``, the ``AutoCheckpoint`` after them."""
    if checkpoint_every is None:
        return callbacks
    if checkpoint is None:
        raise ValidationError(
            f"gemini: checkpoint_every = {checkpoint_every!r}; expected a checkpoint path with it",
            path="checkpoint_every",
        )
    return [*(callbacks or []), AutoCheckpoint(checkpoint, checkpoint_every)]


@contextmanager
def _saved_after(engine, checkpoint):
    """Save the run at its end, also one that stopped early; a run never started saves nothing.

    The save follows the engine's own ``finally``, so the stored results hold their end state.
    """
    try:
        yield
    finally:
        if checkpoint is not None and engine.run_kind is not None:
            engine.to_checkpoint(checkpoint)


def simulate(
    plant,
    case=None,
    plan=None,
    clock=None,
    checkpoint=None,
    checkpoint_every=None,
    backend="numpy",
    callbacks=None,
    on_error="raise",
    compile=True,
):
    """Run ``Engine.simulate`` once and return its ``Results``.

    ``case`` is a ``gm.Case``: its values are set on a copy of ``plant`` for the run, which never
    changes ``plant`` (a plant without the environment it needs raises ``missing_value``), and
    without ``plan`` the run input is ``gm.schedule``'s plan. ``plan`` is the run input, a
    DataFrame or a ``gm.Dataset``, run on the same copy; a ``plan`` that is not from
    ``gm.schedule`` carries the air profile of the case only if it has the column. A building
    block has no demand, so ``case`` may be ``None`` only with a ``plan``; with neither the call
    raises ``ValidationError`` (code ``missing_value``).

    ``checkpoint`` is a path written at the end of the run, also when it stops early (a
    ``gm.errors.Cancelled`` or a failure under ``on_error="raise"``), so ``gm.resume`` can always
    continue it; an existing file is replaced. ``checkpoint_every``, a step count or a duration
    such as ``"1h"``, also writes it during the run and needs ``checkpoint``. ``compile=False``
    forces the eager run. The other arguments are those of ``Engine`` and ``Engine.simulate``.
    """
    if case is None and plan is None:
        raise ValidationError(
            "gemini.simulate: case = None and plan = None; expected a case, a plan or both",
            path="case",
            code="missing_value",
        )
    run_plant, run_input = _planned(plant, case, plan)
    callbacks = _with_autosave(callbacks, checkpoint, checkpoint_every)
    engine = Engine(run_plant, backend, callbacks, on_error, compile)
    with _saved_after(engine, checkpoint):
        return engine.simulate(run_input, clock)


def _planned(plant, case, plan):
    """Return the plant of the run, with the values of ``case``, and its run input."""
    if case is None:
        return plant, plan
    applied = apply_case(plant, case)
    return applied, scheduled(applied, case) if plan is None else plan


def replay(
    plant,
    data,
    start=None,
    end=None,
    state=None,
    clock=None,
    only=None,
    checkpoint=None,
    checkpoint_every=None,
    backend="numpy",
    callbacks=None,
    on_error="raise",
):
    """Run ``Engine.replay`` once and return its ``Results``.

    ``results.end_state`` is the ``state=`` of the next call, so a long replay can go in pieces
    with no object kept between calls. ``checkpoint`` and ``checkpoint_every`` are those of
    ``gm.simulate``; the other arguments are those of ``Engine`` and ``Engine.replay``.
    """
    callbacks = _with_autosave(callbacks, checkpoint, checkpoint_every)
    engine = Engine(plant, backend, callbacks, on_error)
    with _saved_after(engine, checkpoint):
        return engine.replay(data, start, end, state, clock, only)


def live(
    plant,
    source,
    checkpoint,
    step=None,
    now=None,
    sink=None,
    backend="numpy",
    callbacks=None,
    on_error="raise",
):
    """Run ``Engine.live`` once and return the ``Results`` of the new rows.

    ``checkpoint`` is a required path, because nothing else carries a live run between calls: a
    call with a path that does not exist yet starts the run and writes it, every later call
    continues from it and updates it. The other arguments are those of ``Engine`` and
    ``Engine.live``.
    """
    if checkpoint is None:
        raise ValidationError(
            "gemini.live: checkpoint = None; expected a path, which carries the run between calls",
            path="checkpoint",
        )
    return Engine(plant, backend, callbacks, on_error).live(source, checkpoint, step, now, sink)


def resume(checkpoint, callbacks=None):
    """Continue an interrupted ``simulate`` or ``replay`` and return its ``Results``.

    The run continues strictly after the saved position, with the saved backend and error
    policy, gives the results of an uninterrupted run and writes to the same file when it ends
    or stops early. A finished run returns its stored results. A live checkpoint raises
    ``RunError``: ``gm.live`` continues those.
    """
    engine = Engine.from_checkpoint(checkpoint, callbacks)
    if engine.run_kind == "live":
        raise RunError(
            f"{checkpoint}: run_kind = 'live'; expected a simulate or replay checkpoint; "
            "continue a live run with gm.live",
            code="checkpoint",
        )
    with _saved_after(engine, checkpoint):
        return engine.resume()
