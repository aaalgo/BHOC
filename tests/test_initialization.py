import json
from contextlib import chdir
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from bhoc.ai import INITIALIZE, initialize
from bhoc.cli import load_schemas, main
from bhoc.session import Case, CaseFile, new_id
from bhoc.ui import ReadingApp


class FirstCommitTest(IsolatedAsyncioTestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.file = self.enterContext(CaseFile(Path(directory) / "case.json"))
        schema = load_schemas()[0]
        self.case = Case.create(
            self.file, new_id(), "请联网核查项目的当前进展", schema, [7, 8, 8, 6, 9, 9], "manual"
        )
        self.initial_bytes = self.file.path.read_bytes()
        self.candidate = deepcopy(self.case.state)
        self.candidate["bindings"][2].append({
            "id": "item-1", "type": "hypothesis", "content": "尚待查证的进展",
            "interpretation": "核查来源：https://example.org/source",
        })

    async def run_initialization(self, output, *, resume=False):
        tool_output = json.dumps({"bindings": output["bindings"]})
        with patch("bhoc.ai.initialize", return_value=tool_output) as initialize:
            app = ReadingApp(self.case, initialize=True, resume=resume)
            async with app.run_test():
                await app.workers.wait_for_complete()
            initialize.assert_called_once()

    async def test_initialization_saves_first_commit_without_confirmation(self):
        await self.run_initialization(self.candidate)
        saved = self.file.read()
        root, first = saved["session"]["stack"]
        self.assertEqual(first["parent_id"], root["id"])
        self.assertEqual(first["state"], self.candidate)
        self.assertEqual(saved["session"]["conversation"], [])
        self.assertEqual([event["type"] for event in saved["journal"]], ["frame_created", "frame_created"])

    async def test_empty_initialization_preserves_root_and_can_retry(self):
        await self.run_initialization(self.case.state)
        self.assertEqual(self.file.path.read_bytes(), self.initial_bytes)
        self.assertEqual(len(self.case.stack), 1)
        await self.run_initialization(self.candidate, resume=True)
        self.assertEqual(self.file.read()["session"]["stack"][-1]["state"], self.candidate)

    async def test_write_failure_preserves_root(self):
        with patch("bhoc.session.os.replace", side_effect=OSError("模拟写盘失败")):
            await self.run_initialization(self.candidate)
        self.assertEqual(self.file.path.read_bytes(), self.initial_bytes)
        self.assertEqual(len(self.case.stack), 1)

    def test_cli_resume_creates_independent_session(self):
        def save_first_commit():
            resumed, = app.call_args.args
            self.assertEqual(resumed.file.path.parent, self.file.path.parent / "bhoc-sessions")
            self.assertNotEqual(resumed.stamp[0], self.case.stamp[0])
            self.assertEqual(resumed.data["journal"], self.case.data["journal"])
            self.assertEqual(app.call_args.kwargs, {"resume": True, "initialize": True})
            resumed.confirm(resumed.stamp, self.candidate)
            self.assertEqual(resumed.file.read()["session"]["stack"][-1]["state"], self.candidate)

        with chdir(self.file.path.parent), patch("bhoc.cli.ReadingApp") as app:
            app.return_value.run.side_effect = save_first_commit
            self.assertEqual(main(["resume", str(self.file.path)]), 0)
        app.return_value.run.assert_called_once()
        self.assertEqual(self.file.path.read_bytes(), self.initial_bytes)

    def test_search_and_json_conversion_use_separate_models(self):
        items = "1. 二爻 · 假设 · 尚待查证的进展"
        source = "https://example.org/source"
        result = {"bindings": self.candidate["bindings"]}

        def response(text, annotations=()):
            payload = {
                "status": "completed",
                "output": [{"type": "message", "role": "assistant", "content": [
                    {"type": "output_text", "text": text, "annotations": list(annotations)}
                ]}],
            }
            return BytesIO(json.dumps(payload).encode())

        draft = response(items, [{"type": "url_citation", "end_index": len(items), "url": source}])
        formatted = response(json.dumps(result))
        with patch.dict("os.environ", {"BHOC_API_KEY": "test"}, clear=True), patch(
            "bhoc.ai.urlopen", side_effect=[draft, formatted]
        ) as request:
            output = initialize([{"role": "user", "content": INITIALIZE}])
        research, conversion = [json.loads(call.args[0].data) for call in request.call_args_list]
        self.assertEqual(research["model"], "gpt-6.2-astra")
        self.assertEqual(research["tools"], [{"type": "web_search"}])
        self.assertNotIn("text", research)
        self.assertEqual(conversion["model"], "gpt-6.1-terra")
        self.assertNotIn("tools", conversion)
        self.assertEqual(conversion["text"]["format"]["type"], "json_object")
        self.assertIn(items, conversion["input"][-1]["content"])
        self.assertIn(source, conversion["input"][-1]["content"])
        self.assertEqual(json.loads(output), result)
