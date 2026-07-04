class PipelineError(Exception):
    """Raised for expected pipeline failures (missing config, bad input) so the
    worker can record a clean job failure instead of crashing the process."""
