"""Platform-independent local publishing foundation."""

from .foundation import MockPlatformAdapter, PlatformAdapter, PublishingFoundation, publishing_health
from .meta import ExternalUrlMediaHost, MetaHttpClient, MetaInstagramAdapter
from .media_hosting import CloudflareR2MediaHost, MediaHostingError, run_media_hosting
from .controlled import ControlledPublishError, controlled_publish, list_publishable
from .worker import run_worker
from .windows_scheduler import WindowsTaskSchedulerAdapter

__all__ = ["MockPlatformAdapter", "PlatformAdapter", "PublishingFoundation", "publishing_health", "ExternalUrlMediaHost", "CloudflareR2MediaHost", "MediaHostingError", "run_media_hosting", "ControlledPublishError", "controlled_publish", "list_publishable", "MetaHttpClient", "MetaInstagramAdapter", "run_worker", "WindowsTaskSchedulerAdapter"]
