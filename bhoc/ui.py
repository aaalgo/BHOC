"""Textual terminal interface."""
import re
from copy import deepcopy

from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, RichLog, Static

from . import ai
from .core import (BHOCError, SLOTS, VIEWS, derive, diff, fields, list_views, moving_mask, parse_json,
                   require, view_label)
from .display import COMMANDS, delta_text, items_text, state_text, view_text

BASE = {"kind": "base"}
CHANGING = {"kind": "changing"}
NAMED_VIEWS = {label: kind for kind, label in VIEWS.items() if kind != "change"}
CONFIRMATION = ("/confirm", "/cancel", "/quit")


def parse_view(words):
    if len(words) == 1 and words[0] in NAMED_VIEWS:
        return {"kind": NAMED_VIEWS[words[0]]}
    if len(words) > 1 and words[0] == "变":
        lines = words[1:]
        if all(line in "123456" and len(line) == 1 for line in lines) and len(set(lines)) == len(lines):
            return {"kind": "change", "mask": sum(1 << (int(line) - 1) for line in lines)}
    raise BHOCError("用法：/view " + COMMANDS["/view"])


class ChatInput(Input):
    BINDINGS = [Binding("tab", "complete", show=False, priority=True),
                Binding("up", "history(-1)", show=False),
                Binding("down", "history(1)", show=False)]

    def __init__(self):
        super().__init__(placeholder="论卦 >", id="chat-input")
        self.history = []
        self.index = 0
        self.draft = ""

    def remember(self, value):
        self.history.append(value)
        self.index = len(self.history)
        self.draft = ""

    def action_history(self, direction):
        end = len(self.history)
        if self.index == end:
            self.draft = self.value
        self.index = max(0, min(end, self.index + direction))
        self.value = self.history[self.index] if self.index < end else self.draft
        self.cursor_position = len(self.value)

    def action_complete(self):
        prefix = self.value.lstrip()
        if not prefix.startswith("/") or any(character.isspace() for character in prefix):
            return
        commands = CONFIRMATION if self.app.pending is not None else COMMANDS
        matches = [command for command in commands if command.startswith(prefix)]
        if prefix in matches:
            self.value = prefix + " "
        elif len(matches) == 1:
            self.value = matches[0] + " "
        elif matches:
            self.app.write("  ".join(matches))
        self.cursor_position = len(self.value)


class Line(Static):
    def __init__(self, column, slot):
        super().__init__(markup=False, classes="line")
        self.column = column
        self.slot = slot

    def on_click(self):
        self.app.query_one(Hexagrams).focus()
        if self.column and not self.slot:
            self.app.action_choose_view()
        else:
            self.app.select_slot(self.column, self.slot)


class Hexagrams(VerticalScroll):
    can_focus = True

    def compose(self):
        with Horizontal(id="hex-columns"):
            for column in range(2):
                with Vertical(classes="hex-column"):
                    yield Static(markup=False, id=f"hex-title-{column}", classes="hex-title")
                    for slot in (0, 6, 5, 4, 3, 2, 1):
                        yield Line(column, slot)
        yield Static(markup=False, id="bindings")

    def on_key(self, event: events.Key):
        character = event.character
        if character and character.lower() == "v":
            self.app.action_choose_view()
        elif event.key in ("left", "right"):
            self.app.select_slot(int(event.key == "right"), self.app.slot)
        elif character and character in "0123456":
            self.app.select_slot(self.app.column, int(character))
        else:
            return
        event.stop()
        event.prevent_default()


class ViewPicker(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss(None)", "取消", priority=True),
    ]

    def __init__(self, digits):
        super().__init__()
        self.options = [derive(digits, {"kind": kind}) for kind in
                        ("changing", "nuclear", "complement", "reverse")] + list_views(digits)[1:]

    def compose(self):
        with Vertical(id="picker"):
            yield Static("序号   变卦方式       卦")
            yield RichLog(id="choices", markup=False, wrap=True, auto_scroll=False, min_width=1)
            yield Input(placeholder="输入序号 · 回车选择 · Esc 取消", id="choice")
            yield Static("", id="picker-error")

    def on_mount(self):
        log = self.query_one("#choices", RichLog)
        for index, option in enumerate(self.options, 1):
            label = view_label(option["view"])
            log.write(f"{index:>3}   {label:<14} {option['name']}")
        self.query_one(Input).focus()

    @on(Input.Submitted)
    def choose(self, event):
        value = event.value.strip()
        if value.isascii() and value.isdecimal() and len(value) <= 2:
            index = int(value)
            if 1 <= index <= len(self.options):
                self.dismiss(self.options[index - 1]["view"])
                return
        self.query_one("#picker-error", Static).update(f"请输入 1 至 {len(self.options)} 之间的序号")


class ReadingApp(App):
    TITLE = "太卜"
    BINDINGS = [
        Binding("f6", "switch_pane", "切换栏", priority=True),
        Binding("ctrl+d", "quit", "退出", priority=True),
    ]
    CSS = """
    #layout { height: 1fr; }
    #chat { width: 2fr; height: 1fr; }
    #hexagrams { width: 1fr; height: 1fr; border-left: solid $accent; padding: 0 1; }
    RichLog { height: 1fr; }
    #context { height: auto; padding: 0 1; color: $accent; }
    #hex-columns { height: auto; }
    .hex-column { width: 1fr; height: auto; }
    .hex-title { height: 2; }
    .line { height: 1; }
    .line:hover { background: $boost; }
    .selected { background: $accent 30%; }
    #bindings { height: auto; margin-top: 1; }
    #layout.narrow #chat, #layout.narrow #hexagrams { width: 1fr; border: none; }
    #layout.narrow.show-hex #chat, #layout.narrow.show-chat #hexagrams { display: none; }
    #layout.stacked #hex-columns { layout: vertical; }
    #layout.stacked .hex-column { width: 1fr; }
    ViewPicker { align: center middle; }
    #picker { width: 68; max-width: 100%; height: 90%; padding: 1; border: solid $accent; background: $surface; }
    #picker-error { height: 1; color: $error; }
    """

    def __init__(self, case, *, resume=False, initialize=False, provider=None):
        super().__init__()
        self.case = case
        self.resuming = resume
        self.initialize_on_mount = initialize
        self.provider = provider
        self.pending = None
        self.busy = False
        self.on_hex = False
        self.default_view()

    def compose(self) -> ComposeResult:
        with Horizontal(id="layout"):
            with Vertical(id="chat"):
                yield RichLog(wrap=True, markup=False, min_width=1, id="transcript")
                yield Static(markup=False, id="context")
                yield ChatInput()
            yield Hexagrams(id="hexagrams")

    @property
    def view(self):
        return self.related if self.column else BASE

    def default_view(self):
        self.related = CHANGING
        self.column = self.slot = 0

    def on_mount(self):
        self.reading_screen = self.screen
        self.resize_panes(self.size.width)
        self.refresh_hex()
        self.reading_screen.query_one(ChatInput).focus()
        self.write(f"占案文件：{self.case.file.path}")
        self.write(state_text(self.case.state, self.case.data["resources"]["schema"]))
        if self.resuming:
            turns = len(self.case.session["conversation"]) // 2
            self.write(f"当前存案：{self.case.stamp[1]}\n未存案的对话轮数：{turns}")
        self.write("输入 /help 查看命令，按 F6 切换论卦与卦象。")
        if self.initialize_on_mount:
            self.write("太卜正在拟象并挂事，完成后自动建立首条存案。")
            try:
                self.request_ai(initialize=True)
            except (BHOCError, OSError, UnicodeError) as error:
                self.initialization_failed(error)

    def on_resize(self, event: events.Resize):
        if hasattr(self, "reading_screen"):
            self.resize_panes(event.size.width)

    def resize_panes(self, width):
        layout = self.reading_screen.query_one("#layout")
        narrow = width < 108
        layout.set_class(narrow, "narrow")
        layout.set_class(narrow and width < 45, "stacked")
        layout.set_class(self.on_hex, "show-hex")
        layout.set_class(not self.on_hex, "show-chat")

    def action_switch_pane(self):
        if self.screen is not self.reading_screen:
            return
        self.on_hex = self.focused is not self.reading_screen.query_one(Hexagrams)
        self.resize_panes(self.size.width)
        self.reading_screen.query_one(Hexagrams if self.on_hex else ChatInput).focus()

    def on_descendant_focus(self, event):
        if isinstance(event.widget, (ChatInput, Hexagrams)):
            self.on_hex = isinstance(event.widget, Hexagrams)
            self.resize_panes(self.size.width)

    def write(self, text, *, link_urls=False):
        # Treat all user and model text as literal terminal output.
        rendered = Text(text, end="")
        if link_urls:
            for match in re.finditer(r'https?://[^\s<>"]+', rendered.plain):
                url = match.group().rstrip(").,，。；）】")
                rendered.stylize(f"underline link {url}", match.start(), match.start() + len(url))
        self.reading_screen.query_one("#transcript", RichLog).write(rendered)

    def select_slot(self, column, slot):
        self.column, self.slot = column, slot
        self.refresh_hex()

    def refresh_hex(self):
        state = self.case.state
        digits = state["digits"]
        base, related = (derive(digits, view) for view in (BASE, self.related))
        for column, derived in enumerate((base, related)):
            label = view_label(derived["view"])
            heading = f"{label} · {derived['name']}"
            if column:
                heading = "变卦 " + heading
            self.reading_screen.query_one(f"#hex-title-{column}", Static).update(heading)
        for line in self.reading_screen.query(Line):
            column, slot = line.column, line.slot
            if slot:
                derived = related if column else base
                bar = "━━━━━━━" if derived["bits"][slot - 1] else "━━━ ━━━"
                moving = " 动" if not column and moving_mask(digits) & (1 << (slot - 1)) else ""
                line.update(f"[{slot}] {SLOTS[slot]}  {bar}{moving}")
            else:
                line.update("[0] 卦上" if not column else "[V] 选择变卦")
            line.set_class((column, slot) == (self.column, self.slot), "selected")
        source = related["source_lines"][self.slot - 1] if self.column and self.slot else self.slot
        place = SLOTS[self.slot]
        label = view_label(self.view)
        heading = f"{label}{place}"
        if self.column:
            heading += f" ← 本卦{SLOTS[source]}"
        self.reading_screen.query_one("#bindings", Static).update(heading + " · 所挂之事\n" + items_text(state["bindings"][source]))
        self.reading_screen.query_one("#context", Static).update(heading + (" · 太卜正在应答…" if self.busy else ""))

    def set_view(self, view):
        if view is not None:
            if view["kind"] != "base":
                self.related = view
            self.select_slot(int(view["kind"] != "base"), 0)

    def action_choose_view(self):
        if self.pending is not None:
            self.write("请先输入 /confirm、/cancel 或 /quit")
            return
        self.push_screen(ViewPicker(self.case.state["digits"]), self.set_view)

    @on(Input.Submitted, "#chat-input")
    def submit(self, event):
        raw = event.value
        value = raw.lstrip()
        if self.pending is not None and value.strip() in ("", *CONFIRMATION):
            event.input.value = ""
            if value.strip():
                event.input.remember(raw)
            try:
                self.confirmation(value.strip())
            except (BHOCError, OSError, UnicodeError) as error:
                self.write(f"占案操作失败：{error}")
            return
        if not value:
            event.input.value = ""
            return
        if self.pending is not None:
            self.write("请输入 /confirm、/cancel 或 /quit（空行取消）")
            return
        if self.busy and (not value.startswith("/") or value.startswith("//")
                          or value.split()[0] in ("/commit", "/reset")):
            self.write("太卜正在应答，本条输入已保留")
            return
        event.input.remember(raw)
        event.input.value = ""
        try:
            if value.startswith("/") and not value.startswith("//"):
                self.command(*value.split())
            else:
                text = raw if not value.startswith("//") else raw[:len(raw) - len(value)] + value[1:]
                self.request_ai(text)
        except (BHOCError, OSError, UnicodeError) as error:
            self.write(f"占案操作失败：{error}")

    def command(self, command, *args):
        require(command in COMMANDS, f"未知命令 {command}，请用 /help 查看用法")
        if command in ("/state", "/log", "/reset"):
            require(len(args) <= 1, f"用法：{command} {COMMANDS[command]}")
        elif command != "/view":
            require(not args, f"用法：{command}")
        if command == "/quit":
            self.exit()
        elif command == "/help":
            self.write("\n".join(f"{name}  {usage}" for name, usage in COMMANDS.items()))
        elif command == "/state":
            index = self.case.frame_index(args[0]) if args else -1
            self.write(state_text(self.case.stack[index]["state"], self.case.data["resources"]["schema"],
                                  all_slots=True))
        elif command == "/log":
            if not args:
                self.write("\n".join(f"{frame['id']}  {frame['created_at']}" for frame in self.case.stack))
            else:
                index = self.case.frame_index(args[0])
                state = self.case.stack[index]["state"]
                if index:
                    self.write(delta_text(diff(self.case.stack[index - 1]["state"], state)) or "无状态变更")
                else:
                    self.write(state_text(state, self.case.data["resources"]["schema"], all_slots=True))
        elif command == "/view":
            if args:
                self.set_view(parse_view(args))
            self.write(view_text(derive(self.case.state["digits"], self.view)))
        elif command == "/views":
            self.action_choose_view()
        elif command == "/commit":
            self.request_ai()
        elif command == "/reset":
            target = args[0] if args else None
            if target is not None:
                count = len(self.case.stack) - 1 - self.case.frame_index(target)
                self.write(f"复原目标：{target}\n将从有效历史移除 {count} 条存案")
                if count:
                    self.begin_confirmation("reset", target)
                    return
            self.reset_case(target)

    def begin_confirmation(self, operation, value):
        self.pending = (operation, self.case.stamp, value)
        self.write("请输入 /confirm 确认，或 /cancel 取消（空行取消）。")

    def confirmation(self, command):
        if command == "/quit":
            self.pending = None
            self.exit()
        elif command != "/confirm":
            self.pending = None
            self.write("已取消")
        else:
            operation, stamp, value = self.pending
            self.case.check_stamp(stamp)
            if operation == "commit":
                self.case.confirm(stamp, value)
                self.pending = None
                self.refresh_hex()
                self.write(f"本轮存案结束。当前存案：{self.case.stamp[1]}")
            else:
                self.reset_case(value)

    def reset_case(self, target):
        self.case.reset(target)
        self.pending = None
        self.default_view()
        self.refresh_hex()
        self.write(f"已复原。当前存案：{self.case.stamp[1]}")

    def request_ai(self, text=None, *, initialize=False):
        stamp = self.case.stamp
        messages = ai.context(self.case)
        user = None
        if text is not None:
            messages[0]["content"] += "\n用户要求联网核查，或回答依赖近期、易变的事实时，使用网页搜索并注明来源。"
            user = ai.talk_message(self.case.state, text, self.view, self.slot)
            messages.append({"role": "user", "content": user["content"]})
            self.write(f"你：{text}")
        else:
            messages.append({"role": "user", "content": ai.INITIALIZE if initialize else ai.UPDATE})
        self.busy = True
        self.refresh_hex()
        self.ask_model(stamp, deepcopy(messages), user, initialize)

    @work(thread=True)
    def ask_model(self, stamp, messages, user, initialize):
        result, error = None, None
        try:
            if self.provider is not None:
                result = self.provider(messages)
            elif initialize:
                result = ai.initialize(messages)
            else:
                result = ai.complete(messages, web_search=user is not None, json_output=user is None)
        except Exception as exc:
            error = str(exc) if isinstance(exc, BHOCError) else "太卜服务调用失败"
        # Only the UI thread may publish a completed operation.
        try:
            self.call_from_thread(self.finish_ai, stamp, user, result, error, initialize)
        except RuntimeError:
            return  # The app may have exited while the model was running.

    def initialization_failed(self, error):
        self.write(f"首次拟象失败：{error}。起卦记录已保留，退出后可续案重试。")

    def finish_ai(self, stamp, user, result, error, initialize):
        self.busy = False
        if not self.is_running:
            return
        try:
            require(error is None, error)
            self.case.check_stamp(stamp)
            if user is not None:
                require(isinstance(result, str) and result.strip(), "太卜回复为空或无效")
                reply = {"role": "assistant", "content": result, "view": user["view"]}
                self.case.record_turn(stamp, user, reply)
                self.write(f"太卜：{result}", link_urls=True)
            else:
                require(isinstance(result, str), "太卜未返回状态 JSON")
                candidate = parse_json(result)
                if initialize:
                    fields(candidate, ("bindings",), "首次拟象结果")
                    candidate = {**self.case.state, **candidate}
                changes = delta_text(diff(self.case.state, candidate))
                if initialize:
                    require(bool(any(candidate["bindings"])), "首次拟象未返回挂事")
                    self.case.confirm(stamp, candidate)
                    self.write(changes, link_urls=True)
                    self.write(f"首次拟象已存案：{self.case.stamp[1]}")
                else:
                    self.write(changes or "无状态变更，确认后结束本轮")
                    self.begin_confirmation("commit", candidate)
        except (BHOCError, OSError, UnicodeError) as exc:
            if initialize:
                self.initialization_failed(exc)
            else:
                self.write(f"占案操作失败：{exc}")
        finally:
            self.refresh_hex()
