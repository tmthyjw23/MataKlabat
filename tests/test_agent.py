import json
from types import SimpleNamespace

import openai
import pytest

from mataklabat import messages
from mataklabat.agent import AI_LABEL, SECTIONS, TEMPLATE_LABEL, AgentError, IncidentAgent, IncidentReporter, template_report
from mataklabat.config import Resources, Settings
from mataklabat.storage import ReadStore, Storage
from mataklabat.tools import IncidentTools
from tests.test_alerts import CAM, RISK, decision
from tests.test_vision_llm import connection_error

REPORT = "\n\n".join(f"## {s}\nisi {s}" for s in SECTIONS)


def tool_call(name, args, call_id="c1"):
    fn = SimpleNamespace(name=name, arguments=json.dumps(args))
    return SimpleNamespace(id=call_id, type="function", function=fn)


def reply(content=None, calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls))])


class FakeClient:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def settings(tmp_path):
    return Settings(root=tmp_path, cameras=(CAM,), resources=Resources(), llm_model="test/agent", llm_enabled=True)


def make_tools(settings):
    return IncidentTools(settings, risk_provider=lambda: RISK)


def test_agent_uses_tools_then_writes_report(settings):
    client = FakeClient(
        reply(calls=[tool_call("get_weather", {"lat": 1.42, "lon": 124.98}),
                     tool_call("estimate_spread", {"camera_id": "CAM-01", "wind_dir_deg": 270, "wind_kmh": 18}, "c2")]),
        reply(content=REPORT),
    )
    report = IncidentAgent(settings, make_tools(settings), client=client).run(CAM, decision())
    assert report.source == "agent" and report.markdown.startswith(AI_LABEL)
    assert [s["tool"] for s in report.steps] == ["get_weather", "estimate_spread"]
    assert report.steps[1]["result"]["spread_toward"] == "timur"
    second = client.calls[1]["messages"]
    assert second[-2]["role"] == "tool" and second[-2]["tool_call_id"] == "c1"
    assert client.calls[0]["tools"] and client.calls[0]["model"] == "test/agent"
    assert "Kebakaran Terdeteksi karena AI melihat asap" in client.calls[0]["messages"][1]["content"]


def test_agent_step_limit(settings):
    loop = [reply(calls=[tool_call("get_weather", {"lat": 1, "lon": 2}, f"c{i}")]) for i in range(10)]
    with pytest.raises(AgentError):
        IncidentAgent(settings, make_tools(settings), client=FakeClient(*loop)).run(CAM, decision())


def test_agent_empty_answer_is_an_error(settings):
    with pytest.raises(AgentError):
        IncidentAgent(settings, make_tools(settings), client=FakeClient(reply(content="  "))).run(CAM, decision())


def test_template_report_has_all_sections_and_no_invented_data(settings):
    report = template_report(CAM, decision(), make_tools(settings))
    assert report.source == "template" and report.markdown.startswith(TEMPLATE_LABEL)
    for section in SECTIONS:
        assert f"## {section}" in report.markdown
    assert "Hotspot satelit: tidak tersedia" in report.markdown  # no FIRMS key
    assert "Cenderung ke timur" in report.markdown


def make_reporter(settings, agent):
    storage = Storage(settings.db_path)
    queued = []

    def enqueue(incident_id, camera, md):
        queued.append((incident_id, md))
        return storage.enqueue("report", md, incident_id=incident_id)

    return IncidentReporter(settings, storage, make_tools(settings), enqueue, agent), storage, queued


def test_reporter_stores_agent_report_and_queues_message(settings):
    agent = IncidentAgent(settings, make_tools(settings), client=FakeClient(reply(content=REPORT)))
    reporter, storage, queued = make_reporter(settings, agent)
    d = decision()
    incident = storage.open_incident("CAM-01", d.ts, "BAHAYA", None)
    reporter.handle(incident, d)
    row = ReadStore(settings.db_path).incident(incident)
    assert row["report_source"] == "agent" and row["report_md"].startswith(AI_LABEL)
    assert row["report_outbox_id"] is not None and queued[0][0] == incident


@pytest.mark.parametrize("failure", [connection_error(), AgentError("timeout")])
def test_reporter_falls_back_to_template(settings, failure):
    agent = IncidentAgent(settings, make_tools(settings), client=FakeClient(failure))
    reporter, storage, _ = make_reporter(settings, agent)
    incident = storage.open_incident("CAM-01", decision().ts, "BAHAYA", None)
    assert reporter.handle(incident, decision()).source == "template"


def test_reporter_without_llm_and_cooldown(settings):
    reporter, storage, _ = make_reporter(settings, None)
    assert reporter.build(CAM, decision()).source == "template"
    agent = IncidentAgent(settings, make_tools(settings), client=FakeClient(reply(content=REPORT), reply(content=REPORT)))
    reporter.agent = agent
    assert reporter.build(CAM, decision()).source == "agent"
    cooled = reporter.build(CAM, decision())  # same camera within AGENT_COOLDOWN_S
    assert cooled.source == "template" and "dalam 10 menit terakhir" in cooled.markdown.splitlines()[0]


def test_report_message_for_telegram():
    text = messages.report_message(CAM, 3, f"{AI_LABEL}\n\n## Ringkasan\n**Api** di lereng.")
    assert text.startswith("📋 LAPORAN INSIDEN #3 · CAM-01")
    assert "RINGKASAN" in text and "**" not in text and "Dihasilkan AI. Verifikasi lapangan diperlukan." in text
