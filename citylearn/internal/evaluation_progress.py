"""Optional, evaluation-local progress; never retained in KPI results or env state."""
from contextlib import contextmanager, nullcontext
import logging
from time import perf_counter

LOGGER = logging.getLogger(__name__)


class EvaluationProgress:
    def __init__(self, callback):
        if not callable(callback):
            raise TypeError('progress_callback must be callable or None')
        self.callback = callback
        self.started = perf_counter()
        self.sequence = 0
        self.context = {}

    def emit(self, stage, status, **values):
        if self.callback is None:
            return
        self.sequence += 1
        event = dict(self.context, definition_version='evaluation-progress-v1',
                     sequence=self.sequence, stage=stage, status=status,
                     elapsed_seconds=perf_counter() - self.started, **values)
        try:
            self.callback(event)
        except Exception:
            # An observer must not turn a valid numerical evaluation into a failure.
            self.callback = None
            LOGGER.warning('Evaluation progress callback failed; reporting disabled.', exc_info=True)

    @contextmanager
    def span(self, stage, **context):
        previous = self.context
        self.context = dict(previous, **context)
        started = perf_counter()
        self.emit(stage, 'started')
        try:
            yield
        except BaseException as error:
            self.emit(stage, 'failed', stage_seconds=perf_counter() - started,
                      error_type=type(error).__name__)
            raise
        else:
            self.emit(stage, 'completed', stage_seconds=perf_counter() - started)
        finally:
            self.context = previous


def span(reporter, stage, **context):
    return nullcontext() if reporter is None else reporter.span(stage, **context)


def run(reporter, stage, function, *args, **kwargs):
    if reporter is None:
        return function(*args, **kwargs)
    with reporter.span(stage):
        return function(*args, **kwargs)
