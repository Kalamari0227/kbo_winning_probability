import pytest

from kt_championship_engine.models.base import base_win_probability
from kt_championship_engine.models.combine import combine_probabilities


def test_base_probability_home_advantage_is_monotonic(model_features, game):
    home = base_win_probability(game, model_features)
    away_game = game.model_copy(update={"home_team": game.away_team, "away_team": game.home_team})
    away = 1.0 - base_win_probability(away_game, model_features)
    assert home > 0.5
    assert away < home


def test_derived_features_are_marked_mixed(model_features):
    assert {features.feature_quality for features in model_features.values()} == {"mixed"}


def test_jev_failure_is_audited_and_uses_base(game_features, game, config):
    result = combine_probabilities(0.63, None, config)
    assert result.value == pytest.approx(0.63)
    assert result.jev_status == "unavailable"


def test_combined_weight_is_configurable(config, game_features):
    result = combine_probabilities(
        0.60,
        0.80,
        config.model_copy(update={"base_weight": 0.25, "jev_weight": 0.75}),
    )
    assert result.value == pytest.approx(0.75)


def test_combined_probability_is_clipped(config):
    low = combine_probabilities(0.0, 0.0, config)
    high = combine_probabilities(1.0, 1.0, config)
    assert low.value == pytest.approx(0.01)
    assert high.value == pytest.approx(0.99)


def test_missing_jev_key_returns_unavailable_judgment(game, game_features, config, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    from kt_championship_engine.models.jev import HttpJevClient

    judgment = HttpJevClient(config, env_file=None).judge(game, game_features)
    assert judgment.status == "unavailable"
    assert judgment.call_attempted is False


def test_jev_reads_api_key_from_dotenv_and_adds_bearer_scheme(game, game_features, config, tmp_path, monkeypatch):
    import httpx2

    from kt_championship_engine.models.jev import HttpJevClient

    class FakeClient:
        authorization = ""

        def post(self, *args, **kwargs):
            self.authorization = kwargs["headers"]["Authorization"]
            return httpx2.Response(
                200,
                json={
                    "model": "jev-1.13.0",
                    "answers": {
                        component: {"type": "noul", "noul": 0.6}
                        for component in ("starter", "offense", "bullpen", "fatigue", "matchup")
                    },
                },
                request=httpx2.Request("POST", "https://example.test/jev"),
            )

    env_file = tmp_path / ".env"
    env_file.write_text("TYPESAFE_API_KEY=sample-token\n", encoding="utf-8")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    client = FakeClient()
    judgment = HttpJevClient(
        config.model_copy(update={"jev_endpoint": "https://example.test/jev"}),
        client=client,
        env_file=env_file,
    ).judge(game, game_features)

    assert judgment.status == "ok"
    assert client.authorization == "Bearer sample-token"


def test_jev_judgments_are_component_bounded(game, game_features, config):
    from kt_championship_engine.models.jev import MockJevClient

    client = MockJevClient({game.game_id: {"starter": 0.7, "offense": 0.6}})
    judgment = client.judge(game, game_features)
    assert judgment.status == "ok"
    assert judgment.probability == pytest.approx(0.65)


def test_jev_request_is_provenance_bound(game, game_features, config, monkeypatch):
    import httpx2

    from kt_championship_engine.models.jev import HttpJevClient

    class CapturingClient:
        payload = None

        def post(self, *args, **kwargs):
            self.payload = kwargs["json"]
            self.authorization = kwargs["headers"]["Authorization"]
            return httpx2.Response(
                200,
                json={
                    "model": "jev-1.13.0",
                    "answers": {
                        component: {"type": "noul", "noul": 0.6, "confidence": 0.8}
                        for component in ("starter", "offense", "bullpen", "fatigue", "matchup")
                    },
                },
                request=httpx2.Request("POST", "https://example.test/jev"),
            )

    client = CapturingClient()
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    judgment = HttpJevClient(
        config.model_copy(update={"jev_endpoint": "https://example.test/jev"}),
        client=client,
    ).judge(game, game_features)
    assert judgment.status == "ok"
    assert judgment.request_hash is not None and len(judgment.request_hash) == 64
    assert judgment.probability == pytest.approx(0.6)
    assert judgment.model == "jev-1.13.0"
    assert judgment.call_attempted is True
    assert client.authorization == "Bearer test-key"
    assert client.payload["model"] == "jev-latest"
    assert set(client.payload["questions"]) == {"starter", "offense", "bullpen", "fatigue", "matchup"}
    assert client.payload["state"]["analysis_as_of"] == game.as_of.isoformat()
    assert client.payload["state"]["feature_snapshot_hash"] == game_features.snapshot_hash
    assert client.payload["state"]["source"]["source_hash"] == game.source_hash
    assert all(question["type"] == "noul" for question in client.payload["questions"].values())
    assert all(set(question["criteria"]) == {"true", "false"} for question in client.payload["questions"].values())


@pytest.mark.parametrize("body", [[], {"answers": []}, {"answers": {}}])
def test_malformed_jev_envelope_is_audited(game, game_features, config, monkeypatch, body):
    import httpx2

    from kt_championship_engine.models.jev import HttpJevClient

    class FakeClient:
        def post(self, *args, **kwargs):
            return httpx2.Response(200, json=body, request=httpx2.Request("POST", "https://example.test/jev"))

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    judgment = HttpJevClient(
        config.model_copy(update={"jev_endpoint": "https://example.test/jev"}),
        client=FakeClient(),
    ).judge(game, game_features)
    assert judgment.status == "invalid_response"
    assert judgment.call_attempted is True


@pytest.mark.parametrize(
    ("http_status", "expected_status"),
    [(401, "unauthorized"), (403, "forbidden"), (422, "invalid_request"), (429, "rate_limited"), (529, "overloaded")],
)
def test_jev_http_statuses_have_distinct_audit_states(
    game, game_features, config, monkeypatch, http_status, expected_status
):
    import httpx2

    from kt_championship_engine.models.jev import HttpJevClient

    class FakeClient:
        def post(self, *args, **kwargs):
            return httpx2.Response(
                http_status,
                json={"error": "not included in audit message"},
                request=httpx2.Request("POST", "https://example.test/jev"),
            )

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    judgment = HttpJevClient(
        config.model_copy(update={"jev_endpoint": "https://example.test/jev"}),
        client=FakeClient(),
    ).judge(game, game_features)

    assert judgment.status.value == expected_status
    assert judgment.call_attempted is True
    assert "test-key" not in judgment.message

