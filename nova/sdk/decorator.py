"""
Nova SDK Standalone Decorator

Standalone protect decorator for simpler usage without creating Nova instance first.
"""

import functools
from typing import Union, Optional, Callable, List, Any
from pathlib import Path

from .policy import Action


# Global Nova instance for standalone decorator
_default_nova: Optional["Nova"] = None


def get_default_nova() -> "Nova":
    """Get or create the default Nova instance."""
    global _default_nova
    if _default_nova is None:
        from .nova import Nova
        _default_nova = Nova()
    return _default_nova


def set_default_nova(nova: "Nova") -> None:
    """
    Set the default Nova instance for standalone decorator.

    Args:
        nova: Nova instance to use as default
    """
    global _default_nova
    _default_nova = nova


def protect(
    rules_path: Optional[Union[str, Path, List[str]]] = None,
    policy: Optional[dict] = None,
    action: Union[str, Action] = Action.FLAG,
    severity: Optional[str] = None,
    param_name: str = "prompt",
    on_block: Optional[Callable] = None,
    raise_on_block: bool = True,
    nova_instance: Optional["Nova"] = None,
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
):
    """
    Standalone decorator to protect functions with Nova scanning.

    Can be used without creating a Nova instance first. If rules_path or policy
    are provided, creates a new Nova instance. Otherwise uses the default instance.

    Args:
        rules_path: Path to rules (creates new Nova if provided)
        policy: Policy dict (creates new Nova if provided)
        action: Action to take on match
        severity: Minimum severity to trigger
        param_name: Parameter name to scan
        on_block: Handler when blocked
        raise_on_block: Whether to raise exception
        nova_instance: Specific Nova instance to use
        llm_provider: LLM provider for new Nova instance
        llm_model: LLM model for new Nova instance

    Returns:
        Decorator function

    Example:
        from nova.sdk import protect

        @protect(rules_path="nova-rules/", action="block")
        def chat(prompt):
            return openai.chat(prompt)

        # With policy
        @protect(
            rules_path="nova-rules/",
            policy={"PI": {"action": "block"}},
            llm_provider="anthropic"
        )
        async def async_chat(prompt):
            return await claude.messages.create(prompt)
    """
    def decorator(func: Callable) -> Callable:
        nonlocal nova_instance

        if nova_instance is None:
            if rules_path or policy:
                # Create new instance with provided config
                from .nova import Nova
                nova_instance = Nova(
                    rules_path=rules_path,
                    policy=policy,
                    llm_provider=llm_provider,
                    llm_model=llm_model
                )
            else:
                nova_instance = get_default_nova()

        # Use the Nova instance's protect method
        return nova_instance.protect(
            action=action,
            severity=severity,
            param_name=param_name,
            on_block=on_block,
            raise_on_block=raise_on_block,
        )(func)

    return decorator


def scan(
    text: str,
    rules_path: Optional[Union[str, Path, List[str]]] = None,
    policy: Optional[dict] = None,
    nova_instance: Optional["Nova"] = None,
) -> "ScanResult":
    """
    Standalone scan function for quick scanning without instance management.

    Args:
        text: Text to scan
        rules_path: Path to rules (creates new Nova if provided)
        policy: Policy dict (creates new Nova if provided)
        nova_instance: Specific Nova instance to use

    Returns:
        ScanResult with match details

    Example:
        from nova.sdk import scan

        result = scan("ignore previous instructions", rules_path="nova-rules/")
        if result.blocked:
            print("Blocked!")
    """
    if nova_instance is None:
        if rules_path or policy:
            from .nova import Nova
            nova_instance = Nova(rules_path=rules_path, policy=policy)
        else:
            nova_instance = get_default_nova()

    return nova_instance.scan(text)


async def scan_async(
    text: str,
    rules_path: Optional[Union[str, Path, List[str]]] = None,
    policy: Optional[dict] = None,
    nova_instance: Optional["Nova"] = None,
) -> "ScanResult":
    """
    Async standalone scan function.

    Args:
        text: Text to scan
        rules_path: Path to rules (creates new Nova if provided)
        policy: Policy dict (creates new Nova if provided)
        nova_instance: Specific Nova instance to use

    Returns:
        ScanResult with match details
    """
    if nova_instance is None:
        if rules_path or policy:
            from .nova import Nova
            nova_instance = Nova(rules_path=rules_path, policy=policy)
        else:
            nova_instance = get_default_nova()

    return await nova_instance.scan_async(text)
