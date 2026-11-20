__version__ = '3.6.0'

# CityLearn does not configure logging. Without application configuration, Python's last-resort handler
# still prints WARNING and above to stderr; configure logging (e.g. logging.basicConfig) to see INFO.

__all__ = ["MultiCommunityEnv", "__version__"]


def __getattr__(name: str):
    if name == "MultiCommunityEnv":
        from citylearn.multi_community import MultiCommunityEnv

        return MultiCommunityEnv

    raise AttributeError(f"module 'citylearn' has no attribute {name!r}")
