from __future__ import annotations

import logging

from storage_base import StorageBase
from storage_cleanup import StorageCleanupMixin
from storage_recovery import StorageRecoveryMixin
from storage_repository import StorageRepositoryMixin
from storage_schema import StorageSchemaMixin
from storage_search import StorageSearchMixin

logger = logging.getLogger(__name__)


class StorageManager(
    StorageCleanupMixin,
    StorageRecoveryMixin,
    StorageSearchMixin,
    StorageRepositoryMixin,
    StorageSchemaMixin,
    StorageBase,
):
    def __init__(self, db_path: str, repo_root: str, upload_dir: str):
        super().__init__(db_path, repo_root, upload_dir)
        self._init_db()
        self._check_migration()

