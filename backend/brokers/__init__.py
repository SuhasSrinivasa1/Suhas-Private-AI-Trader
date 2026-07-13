"""Broker adapter package.

All real broker integrations must implement the shared adapter interface and keep
credentials outside source control. Paper mode is the only enabled execution mode
in the current application.
"""

from .paper import PaperBroker

__all__ = ["PaperBroker"]
