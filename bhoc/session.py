"""Locked case files and transactional journal operations."""
import fcntl
import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from .core import BHOCError, diff, fields, nonempty, parse_json, require, validate_state, validate_view

VERSIONS = {"core_version": "0.3", "calculus_version": "0.3"}


def now():
    return datetime.now(timezone.utc).isoformat()


def new_id():
    return str(uuid4())


def validate_id(value):
    try:
        require(isinstance(value, str) and str(UUID(value)) == value, "标识须为 UUID")
    except ValueError as error:
        raise BHOCError("占案或存案标识须为 UUID") from error


def validate_time(value):
    try:
        require(isinstance(value, str) and datetime.fromisoformat(value).utcoffset() is not None,
                "事件时间须含时区")
    except ValueError as error:
        raise BHOCError("事件时间无效") from error


def validate_schema(schema):
    fields(schema, ("id", "version", "name", "body"), "固定易例")
    require(all(map(nonempty, schema.values())), "固定易例的字段不能为空")


def validate_case(data):
    fields(data, ("format_version", "session", "journal", "casting", "resources"), "占案")
    require(type(data["format_version"]) is int and data["format_version"] == 1, "占案文件版本不受支持")
    resources = data["resources"]
    fields(resources, (*VERSIONS, "schema"), "资源")
    require(all(resources[key] == value for key, value in VERSIONS.items()), "演算协议或核心版本不受支持")
    schema = resources["schema"]
    validate_schema(schema)
    casting = data["casting"]
    fields(casting, ("method", "created_at"), "起卦资料")
    require(casting["method"] in ("manual", "three_coins_os"), "起卦方式无效")
    validate_time(casting["created_at"])
    session = data["session"]
    fields(session, ("id", "stack", "conversation", "conversation_version"), "占案状态")
    validate_id(session["id"])
    events = data["journal"]
    require(isinstance(events, list) and events, "日志须包含起卦记录")
    stack, conversation, seen = [], [], set()
    for index, event in enumerate(events):
        require(isinstance(event, dict), "日志事件无效")
        kind = event.get("type")
        if kind == "frame_created":
            fields(event, ("type", "frame"), "新存案事件")
            frame = event["frame"]
            fields(frame, ("id", "parent_id", "created_at", "state"), "存案")
            validate_id(frame["id"])
            validate_time(frame["created_at"])
            require(frame["id"] not in seen, "日志中的存案标识重复")
            require(frame["parent_id"] == (stack[-1]["id"] if stack else None), "存案父链与有效历史不符")
            validate_state(frame["state"], stack[0]["state"] if stack else None)
            if index == 0:
                require(frame["state"]["schema"] == {key: schema[key] for key in ("id", "version")},
                        "起卦易例与固定易例不符")
                require(frame["created_at"] == casting["created_at"], "起卦时间与日志不符")
                require(not any(frame["state"]["bindings"]), "起卦记录须包含七处空挂")
            stack.append(frame)
            seen.add(frame["id"])
            conversation.clear()
            continue

        require(bool(stack), "日志首项须为起卦记录")
        validate_time(event.get("created_at"))
        top = stack[-1]["id"]
        if kind == "chat_turn":
            fields(event, ("type", "created_at", "frame_id", "user", "assistant"), "对话事件")
            require(event["frame_id"] == top, "对话引用的存案与有效栈顶不符")
            for role in ("user", "assistant"):
                message = event[role]
                fields(message, ("role", "content"), "对话消息", ("view",))
                require(message["role"] == role and nonempty(message["content"]), "对话消息无效")
                if "view" in message:
                    validate_view(message["view"])
                conversation.append(message)
        elif kind == "reset":
            fields(event, ("type", "created_at", "from_frame_id", "to_frame_id"), "复原事件")
            ids = [frame["id"] for frame in stack]
            require(event["from_frame_id"] == top and event["to_frame_id"] in ids, "复原引用无效")
            del stack[ids.index(event["to_frame_id"]) + 1:]
            conversation.clear()
        elif kind == "commit_unchanged":
            fields(event, ("type", "created_at", "frame_id"), "空差异存案事件")
            require(event["frame_id"] == top, "空差异事件引用无效")
            conversation.clear()
        else:
            raise BHOCError("日志事件类型无效")

    def same(left, right):
        return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)

    require(same(session["stack"], stack), "日志重建的有效栈与占案不符")
    require(same(session["conversation"], conversation), "日志重建的临时对话与占案不符")
    version = session["conversation_version"]
    require(type(version) is int and version == len(events) - 1, "临时对话版本与日志不符")


class CaseFile:
    def __init__(self, path):
        self.path = Path(path).resolve()

    def __enter__(self):
        self.lock = self.path.with_name(self.path.name + ".lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.lock.close()
            if isinstance(error, BlockingIOError):
                raise BHOCError("占案正由另一终端使用") from error
            raise
        return self

    def __exit__(self, *exc):
        self.lock.close()

    def read(self):
        data = parse_json(self.path.read_text(encoding="utf-8"))
        validate_case(data)
        return data

    def write(self, data, *, create=False):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".bhoc-", delete=False) as file:
                temporary = Path(file.name)
                json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            if create:
                try:
                    os.link(temporary, self.path)
                except FileExistsError as error:
                    raise BHOCError("占案文件已存在，请使用 bhoc resume 续案") from error
            else:
                os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


class Case:
    def __init__(self, file, data):
        self.file = file
        self.data = data

    @classmethod
    def create(cls, file, session_id, question, schema, digits, method):
        validate_schema(schema)
        state = {"question": question, "schema": {key: schema[key] for key in ("id", "version")},
                 "digits": digits, "bindings": [[] for _ in range(7)]}
        frame = {"id": new_id(), "parent_id": None, "created_at": now(), "state": state}
        data = {
            "format_version": 1,
            "session": {"id": session_id, "stack": [frame], "conversation": [], "conversation_version": 0},
            "journal": [{"type": "frame_created", "frame": frame}],
            "casting": {"method": method, "created_at": frame["created_at"]},
            "resources": {**VERSIONS, "schema": schema},
        }
        validate_case(data)
        file.write(data, create=True)
        return cls(file, data)

    @property
    def session(self):
        return self.data["session"]

    @property
    def stack(self):
        return self.session["stack"]

    @property
    def state(self):
        return self.stack[-1]["state"]

    @property
    def stamp(self):
        return self.session["id"], self.stack[-1]["id"], self.session["conversation_version"]

    def frame_index(self, frame_id):
        for index, frame in enumerate(self.stack):
            if frame["id"] == frame_id:
                return index
        raise BHOCError("有效存案栈中没有该存案 ID")

    def save(self, session, event):
        session["conversation_version"] += 1
        data = {**self.data, "session": session, "journal": [*self.data["journal"], event]}
        self.file.write(data)
        self.data = data

    def check_stamp(self, stamp):
        require(stamp == self.stamp, "栈顶或临时对话已改变，请重试")

    def record_turn(self, stamp, user, assistant):
        self.check_stamp(stamp)
        session = deepcopy(self.session)
        session["conversation"].extend((user, assistant))
        self.save(session, {"type": "chat_turn", "created_at": now(), "frame_id": stamp[1],
                            "user": user, "assistant": assistant})

    def confirm(self, stamp, candidate):
        self.check_stamp(stamp)
        delta = diff(self.state, candidate)
        session = deepcopy(self.session)
        session["conversation"].clear()
        if delta["items"] or "question" in delta:
            frame = {"id": new_id(), "parent_id": stamp[1], "created_at": now(),
                     "state": deepcopy(candidate)}
            session["stack"].append(frame)
            event = {"type": "frame_created", "frame": frame}
        else:
            event = {"type": "commit_unchanged", "created_at": now(), "frame_id": stamp[1]}
        self.save(session, event)

    def reset(self, target=None):
        index = len(self.stack) - 1 if target is None else self.frame_index(target)
        session = deepcopy(self.session)
        del session["stack"][index + 1:]
        session["conversation"].clear()
        self.save(session, {"type": "reset", "created_at": now(), "from_frame_id": self.stamp[1],
                            "to_frame_id": session["stack"][-1]["id"]})
