"""M16 skill execution exceptions."""


class SkillSecurityError(Exception):
    """Skill violated security policy (forbidden module, blocked URL, etc.)."""


class SkillTimeoutError(Exception):
    """Skill execution exceeded its timeout."""


class SkillExecutionError(Exception):
    """Skill execution failed for any other reason (syntax error, runtime, etc.)."""
