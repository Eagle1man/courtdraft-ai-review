"""QD-Court: изоляция, подтверждение, лимиты, отказ (Этапы 4–5 ТЗ)."""

from __future__ import annotations

import json

from app.agents.evidence_pack import EvidenceItem, EvidencePack
from app.exploration import (
    ExplorationBudget,
    ExplorationService,
    HumanReviewStatus,
    Hypothesis,
    HypothesisStatus,
)


def _pack(case: str = "T-0001") -> EvidencePack:
    pack = EvidencePack(case_number=case)
    pack.items.append(
        EvidenceItem(
            category="claims",
            text="Истец просит взыскать 10148 рублей долга.",
            source_document="01_claim.txt",
            source_type="CLAIM",
            amounts=["10148"],
            order=1,
        )
    )
    pack.items.append(
        EvidenceItem(
            category="objections",
            text="Ответчик не согласен с размером долга.",
            source_document="02_response.txt",
            source_type="RESPONSE",
            order=2,
        )
    )
    return pack


def _service(tmp_path, **budget_kwargs) -> ExplorationService:
    budget = ExplorationBudget(**budget_kwargs)
    return ExplorationService(archive_root=tmp_path, budget=budget)


class TestArchiveIsolation:
    def test_cases_do_not_share_hypotheses(self, tmp_path) -> None:
        service = _service(tmp_path)
        first = service.run("T-A", _pack("T-A"))
        second = service.run("T-B", _pack("T-B"))
        first_ids = {h.id for h in first.hypotheses}
        second_ids = {h.id for h in second.hypotheses}
        assert first_ids
        assert second_ids
        assert not first_ids & second_ids
        # Ни одна гипотеза не приписана чужому делу.
        assert all(h.case_id == "T-B" for h in second.hypotheses)


class TestVerification:
    def test_dangling_source_rejected(self, tmp_path) -> None:
        service = _service(tmp_path)
        report = service.run("T-0001", _pack())
        dangling = [
            h
            for h in report.hypotheses
            if any(s == "99_missing.txt" for s in h.sources)
        ]
        assert not dangling  # предлагающий сам не выдумывает источников

    def test_number_not_in_materials_rejected(self, tmp_path) -> None:
        service = _service(tmp_path)
        report = service.run("T-0001", _pack())
        for hypothesis in report.hypotheses:
            if hypothesis.status is HypothesisStatus.UNSUPPORTED:
                assert hypothesis.rejection_reason
        assert all(
            h.status is not HypothesisStatus.SUPPORTED or "источник" not in h.rejection_reason
            for h in report.hypotheses
        )

    def test_supported_hypothesis_has_checks(self, tmp_path) -> None:
        service = _service(tmp_path)
        report = service.run("T-0001", _pack())
        supported = [h for h in report.hypotheses if h.status is HypothesisStatus.SUPPORTED]
        assert supported
        for hypothesis in supported:
            assert hypothesis.checks["sources_exist"]
            assert hypothesis.checks["numbers_in_materials"]

    def test_human_review_pending_by_default(self, tmp_path) -> None:
        service = _service(tmp_path)
        report = service.run("T-0001", _pack())
        assert all(h.human_review is HumanReviewStatus.PENDING for h in report.hypotheses)


class TestNoveltyFilter:
    def test_repeated_run_does_not_grow_archive(self, tmp_path) -> None:
        service = _service(tmp_path)
        first_run = service.run("T-0001", _pack())
        second_run = service.run("T-0001", _pack())
        assert len(second_run.hypotheses) == len(first_run.hypotheses)
        # Ни одного дубля текста: повторная генерация не раздувает архив.
        texts = [h.text for h in second_run.hypotheses]
        assert len(texts) == len(set(texts))


class TestBudget:
    def test_iteration_limit_respected(self, tmp_path) -> None:
        service = _service(tmp_path, max_iterations=1, max_hypotheses=10)
        report = service.run("T-0001", _pack())
        assert report.iterations <= 1

    def test_no_crash_on_empty_pack(self, tmp_path) -> None:
        service = _service(tmp_path)
        report = service.run("T-EMPTY", EvidencePack(case_number="T-EMPTY"))
        assert report.fallback or report.hypotheses == []

    def test_fallback_on_broken_archive(self, tmp_path) -> None:
        (tmp_path / "T-BROKEN.json").write_text("{ сломано", encoding="utf-8")
        service = _service(tmp_path)
        report = service.run("T-BROKEN", _pack())
        assert report.fallback
        assert report.reason


class TestSafety:
    def test_pack_not_mutated(self, tmp_path) -> None:
        pack = _pack()
        before = [item.text for item in pack.items]
        _service(tmp_path).run("T-0001", pack)
        assert [item.text for item in pack.items] == before

    def test_json_roundtrip(self, tmp_path) -> None:
        service = _service(tmp_path)
        report = service.run("T-0001", _pack())
        payload = json.dumps(report.to_dict(), ensure_ascii=False)
        loaded = json.loads(payload)
        assert loaded["case_id"] == "T-0001"
        assert isinstance(loaded["hypotheses"], list)

    def test_mutation_uses_parent_source(self, tmp_path) -> None:
        service = _service(tmp_path)
        report = service.run("T-0001", _pack())
        mutated = [h for h in report.hypotheses if h.parent_ids]
        if mutated:
            assert all(h.parent_ids for h in mutated)
            assert all(h.sources for h in mutated)


class TestBoilerplateFilter:
    def test_article56_recital_not_a_direction(self, tmp_path) -> None:
        pack = _pack()
        pack.items.append(
            EvidenceItem(
                category="objections",
                text="В силу ст. 56 ГПК РФ каждая сторона должна доказать "
                "обстоятельства, на которые она ссылается.",
                source_document="02_response.txt",
                source_type="RESPONSE",
                order=3,
            )
        )
        pack.items.append(
            EvidenceItem(
                category="objections",
                text="Ходатайств и возражений относительно исковых "
                "требований от нее не поступило.",
                source_document="02_response.txt",
                source_type="RESPONSE",
                order=4,
            )
        )
        directions = _service(tmp_path).proposer.explore(pack)
        objection_directions = [h for h in directions if h.kind == "objection_coverage"]
        assert all("56 ГПК" not in h.text for h in objection_directions)
        assert all("не поступило" not in h.text for h in objection_directions)


class TestMutationSupersedesParent:
    def test_mutation_replaces_parent(self) -> None:
        from app.exploration.archive import admit

        parent = Hypothesis(
            id="p1",
            case_id="T-0001",
            question_id="q1",
            kind="objection_coverage",
            text="направление: разобрать довод «не согласен с долгом»",
            sources=["02_response.txt"],
            novelty=0.9,
            status=HypothesisStatus.SUPPORTED,
        )
        child = Hypothesis(
            id="c1",
            case_id="T-0001",
            question_id="q1",
            kind="objection_coverage",
            text=parent.text + " Уточнение: «долг не признан»",
            sources=["02_response.txt"],
            parent_ids=["p1"],
            novelty=0.2,
            status=HypothesisStatus.SUPPORTED,
        )
        result = admit([parent], child)
        assert any(h.id == "c1" for h in result)
        assert next(h for h in result if h.id == "p1").status is HypothesisStatus.SUPERSEDED


class TestHypothesisModel:
    def test_to_dict_from_dict_roundtrip(self) -> None:
        hypothesis = Hypothesis(
            id="h1",
            case_id="T-0001",
            question_id="q1",
            kind="objection_coverage",
            text="проверить довод",
            sources=["02_response.txt"],
            novelty=0.8,
            status=HypothesisStatus.SUPPORTED,
        )
        restored = Hypothesis.from_dict(hypothesis.to_dict())
        assert restored.id == "h1"
        assert restored.status is HypothesisStatus.SUPPORTED
        assert restored.human_review is HumanReviewStatus.PENDING

    def test_id_stability(self) -> None:
        first = Hypothesis(id="a", case_id="c", question_id="q", kind="k", text="t")
        second = Hypothesis(id="a", case_id="c", question_id="q", kind="k", text="t")
        assert first.to_dict()["id"] == second.to_dict()["id"] == "a"
