"""The error hierarchy. Every failure Taller reports is one of these."""


class TallerError(Exception):
    """Base class. Carries a message meant for the owner, not a stack trace."""


class ConfigError(TallerError):
    """Configuration is missing, malformed, or contradictory."""


class LockTimeout(TallerError):
    """A lock could not be taken within its timeout."""


class InferenceError(TallerError):
    """A dispatch to the `claude` CLI failed."""


class GitError(TallerError):
    """A git operation failed."""


class NotOnMain(GitError):
    """The owner's checkout is on another branch, so `main` is not Taller's to write."""


class UncommittedWork(GitError):
    """The owner's checkout has changes nobody has committed; Taller leaves them be."""


class DoctorFailure(TallerError):
    """A doctor check failed."""
