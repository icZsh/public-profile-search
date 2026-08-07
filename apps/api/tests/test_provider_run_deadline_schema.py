from apps.api.app.models.entities import ProviderRun, SearchJob


def test_provider_run_deadline_is_nullable_for_unbounded_synthesis() -> None:
    assert ProviderRun.__table__.c.deadline_at.nullable is True


def test_job_deadlines_remain_required_for_bounded_retrieval() -> None:
    assert SearchJob.__table__.c.collection_cutoff_at.nullable is False
    assert SearchJob.__table__.c.fallback_at.nullable is False
    assert SearchJob.__table__.c.deadline_at.nullable is False
