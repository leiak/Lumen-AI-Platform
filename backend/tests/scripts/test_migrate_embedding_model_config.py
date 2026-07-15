"""Tests for the embedding_model_config_id startup migration script."""
import pytest
from unittest.mock import MagicMock


class _FakeConfig:
    def __init__(self, id, tenant_id, model_type, model_name,
                 is_active=True, is_chat=True, is_embedding=False):
        self.id = id
        self.tenant_id = tenant_id
        self.model_type = model_type
        self.model_name = model_name
        self.is_active = is_active
        self.is_chat = is_chat
        self.is_embedding = is_embedding


class _FakeKB:
    def __init__(self, id, tenant_id, embedding_model,
                 embedding_model_config_id=None):
        self.id = id
        self.tenant_id = tenant_id
        self.embedding_model = embedding_model
        self.embedding_model_config_id = embedding_model_config_id
        self.documents = []


class _FakeDoc:
    def __init__(self, id, knowledge_base_id, embedding_model_config_id=None):
        self.id = id
        self.knowledge_base_id = knowledge_base_id
        self.embedding_model_config_id = embedding_model_config_id


class TestMigrateEmbeddingModelConfig:
    def _setup(self):
        """Build a minimal fake-DB with the query API the script uses.

        The script instantiates real ``ModelConfig`` (not a fake) when
        it needs to create a new row, so the ``add`` handler detects
        type by duck-typing on attribute names rather than ``isinstance``.
        """
        kbs = []
        docs = []
        configs = []
        config_index = {}
        next_id = [0]

        db = MagicMock()

        def add(obj):
            next_id[0] += 1
            obj.id = next_id[0]
            # Detect by attributes: ModelConfig has model_name+model_type;
            # KnowledgeBase has embedding_model; Document has knowledge_base_id.
            if hasattr(obj, "model_name") and hasattr(obj, "model_type"):
                configs.append(obj)
                config_index[(obj.tenant_id, obj.model_type, obj.model_name)] = obj
            elif hasattr(obj, "embedding_model") and not hasattr(obj, "knowledge_base_id"):
                kbs.append(obj)
            elif hasattr(obj, "knowledge_base_id"):
                docs.append(obj)

        db.add.side_effect = add
        db.commit = MagicMock()
        db.flush = MagicMock()

        def query(model):
            m = MagicMock()
            m.filter.return_value.first.return_value = None
            if hasattr(model, "__name__"):
                if model.__name__ == "KnowledgeBase":
                    m.all.return_value = kbs
                elif model.__name__ == "Document":
                    m.all.return_value = docs
            return m

        db.query.side_effect = query
        return db, kbs, docs, configs, config_index

    def test_creates_config_and_links_kb(self):
        """A KB with embedding_model='nomic-embed-text' and tenant_id=1
        gets a new ModelConfig row with is_embedding=True, and the KB
        is updated."""
        from lumen_scripts.migrate_embedding_model_config import (
            migrate_embedding_model_config,
        )

        db, kbs, docs, configs, _ = self._setup()
        kbs.append(_FakeKB(id=1, tenant_id=1, embedding_model="nomic-embed-text"))

        report = migrate_embedding_model_config(db)

        assert len(configs) == 1
        cfg = configs[0]
        assert cfg.model_type == "ollama"
        assert cfg.model_name == "nomic-embed-text"
        assert cfg.is_embedding is True
        assert cfg.is_chat is False
        # KB is back-linked
        assert kbs[0].embedding_model_config_id == cfg.id
        assert report.kbs_scanned == 1
        assert report.kbs_linked == 1
        assert report.configs_created == 1

    def test_idempotent_second_run_does_nothing(self):
        """Running the migration twice produces no extra writes."""
        from lumen_scripts.migrate_embedding_model_config import (
            migrate_embedding_model_config,
        )

        db, kbs, docs, configs, _ = self._setup()
        kbs.append(_FakeKB(id=1, tenant_id=1, embedding_model="nomic-embed-text"))

        migrate_embedding_model_config(db)
        first_count = len(configs)
        first_kb_id = kbs[0].embedding_model_config_id

        # Patch _find_config to return the existing config on second run.
        from lumen_scripts import migrate_embedding_model_config as mod
        original_find = mod._find_config

        def fake_find(db, tenant_id, model_name):
            return configs[0] if configs else None

        mod._find_config = fake_find
        try:
            report = migrate_embedding_model_config(db)
        finally:
            mod._find_config = original_find

        assert len(configs) == first_count
        assert kbs[0].embedding_model_config_id == first_kb_id
        assert report.kbs_linked == 0
        assert report.kbs_already_linked == 1

    def test_documents_backfilled_from_kb(self):
        """Docs whose embedding_model_config_id is NULL inherit the KB's FK."""
        from lumen_scripts.migrate_embedding_model_config import (
            migrate_embedding_model_config,
        )

        db, kbs, docs, configs, _ = self._setup()
        kb = _FakeKB(id=10, tenant_id=1, embedding_model="nomic-embed-text")
        kbs.append(kb)
        d1 = _FakeDoc(id=100, knowledge_base_id=10)
        d2 = _FakeDoc(id=101, knowledge_base_id=10)
        docs.append(d1)
        docs.append(d2)
        kb.documents = [d1, d2]

        migrate_embedding_model_config(db)

        assert kbs[0].embedding_model_config_id is not None
        assert d1.embedding_model_config_id == kbs[0].embedding_model_config_id
        assert d2.embedding_model_config_id == kbs[0].embedding_model_config_id
