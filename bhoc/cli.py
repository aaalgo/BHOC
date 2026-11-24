"""Command-line entry point and casting wizard."""
import re
import sys
from pathlib import Path

from textual import on
from textual.app import App
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, Static

from .core import DATA, BHOCError, cast_coins, require, validate_digits
from .session import Case, CaseFile, new_id, validate_schema
from .ui import ReadingApp

USAGE = "用法：bhoc [占案文件]\n      bhoc resume <占案文件>"


def load_schemas():
    schemas = {}
    for directory in (DATA / "schemas", Path.cwd() / "schemas"):
        for path in sorted(directory.glob("*.md")):
            try:
                opening, metadata, body = re.split(r"(?m)^---[ \t]*$", path.read_text(encoding="utf-8"), maxsplit=2)
                require(not opening.strip(), "易例须以 Markdown 元数据开头")
                schema = {"body": body.strip()}
                for line in metadata.strip().splitlines():
                    key, sep, value = line.partition(":")
                    key = key.strip()
                    require(sep and key in ("id", "version", "name") and key not in schema,
                            "易例元数据须包含 id、version、name")
                    schema[key] = value.strip()
                validate_schema(schema)
                ref = schema["id"], schema["version"]
                require(ref not in schemas or schemas[ref] == schema, "相同版本的易例内容不一致")
                schemas[ref] = schema
            except (ValueError, OSError) as error:
                raise BHOCError(f"无法加载易例 {path}：{error}") from error
    return sorted(schemas.values(), key=lambda schema: schema["id"] != "general")


class Wizard(App):
    TITLE = "新建占案"
    BINDINGS = [Binding(key, "quit", "取消", priority=True) for key in ("escape", "ctrl+d")]
    CSS = """
    Screen { align: center middle; }
    #wizard { width: 72; max-width: 100%; height: auto; max-height: 100%;
              overflow-y: auto; padding: 1; border: solid $accent; }
    #error { height: auto; color: $error; }
    """

    def __init__(self, schemas):
        super().__init__()
        self.schemas = schemas
        self.step = "schema"
        self.schema = None
        self.question = None

    def compose(self):
        with Vertical(id="wizard"):
            choices = "\n".join(f"{i}. {schema['name']} · {schema['version']}"
                                for i, schema in enumerate(self.schemas, 1))
            yield Static("择易例\n" + choices, markup=False, id="prompt")
            yield Input(placeholder="输入易例序号")
            yield Static("", id="error", markup=False)
            yield Static("回车继续 · Esc 取消")

    def prompt(self, text, hint):
        self.query_one("#prompt", Static).update(text)
        self.query_one(Input).placeholder = hint

    @on(Input.Submitted)
    def advance(self, event):
        answer = event.value.strip()
        error = self.query_one("#error", Static)
        error.update("")
        try:
            if self.step == "schema":
                count = len(self.schemas)
                require(answer in {str(i) for i in range(1, count + 1)}, f"请输入 1 至 {count} 之间的易例序号")
                self.schema = self.schemas[int(answer) - 1]
                self.step = "question"
                self.prompt("请述所闻之事", "可一并输入背景与分析约束")
            elif self.step == "question":
                require(answer, "所闻之事不能为空")
                self.question = answer
                self.step = "method"
                self.prompt("起卦\n1. 三钱起卦\n2. 输入数字卦", "输入起卦方式序号")
            elif self.step == "method":
                require(answer in ("1", "2"), "请输入 1 或 2")
                if answer == "1":
                    self.exit((self.question, self.schema, cast_coins(), "three_coins_os"))
                else:
                    self.step = "digits"
                    self.prompt("输入数字卦", "初爻至上爻的六个整数，以空格分隔")
            else:
                parts = answer.split()
                require(all(part in ("6", "7", "8", "9") for part in parts), "数字卦只接受 6 至 9")
                digits = list(map(int, parts))
                validate_digits(digits)
                self.exit((self.question, self.schema, digits, "manual"))
            event.input.value = ""
        except BHOCError as exc:
            error.update(str(exc))


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["--help"], ["-h"]):
        print(USAGE)
        return 0
    resume = bool(args and args[0] == "resume")
    paths = args[1:] if resume else args
    if len(paths) > 1 or (resume and len(paths) != 1) or any(arg.startswith("-") for arg in paths):
        print(USAGE, file=sys.stderr)
        return 2
    session_id = None if resume else new_id()
    path = Path(paths[0]) if paths else Path("bhoc-sessions") / f"{session_id}.json"
    try:
        if resume:
            require(path.is_file(), "占案文件不存在或不是普通文件")
            with CaseFile(path) as file:
                case = Case(file, file.read())
                ReadingApp(case, resume=True, initialize=len(case.data["journal"]) == 1).run()
        else:
            require(not (path.exists() or path.is_symlink()), "占案文件已存在，请使用 bhoc resume 续案")
            setup = Wizard(load_schemas()).run()
            if setup is None:
                return 0
            path.parent.mkdir(parents=True, exist_ok=True)
            with CaseFile(path) as file:
                case = Case.create(file, session_id, *setup)
                ReadingApp(case, initialize=True).run()
    except (BHOCError, OSError, UnicodeError) as exc:
        print(f"占案操作失败：{exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        return 0
    return 0
