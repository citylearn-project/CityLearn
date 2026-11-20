import logging

__version__ = '3.6.0'

# Library logging: no output unless the application configures logging.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = ["MultiCommunityEnv", "__version__"]


def __getattr__(name: str):
    if name == "MultiCommunityEnv":
        from citylearn.multi_community import MultiCommunityEnv

        return MultiCommunityEnv

    raise AttributeError(f"module 'citylearn' has no attribute {name!r}")
