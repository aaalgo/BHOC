"""Chinese text for commands and case summaries."""
from .core import SLOTS, TYPES, derive, moving_mask, view_label

COMMANDS = {
    "/help": "显示命令及参数说明",
    "/state": "[存案ID]  查看当前或历史状态",
    "/log": "[存案ID]  查看有效存案或相对父案的差异",
    "/view": "[本卦|之卦|互卦|错卦|综卦|变 <爻位...>]  查看或切换视角",
    "/views": "打开变卦选择窗",
    "/commit": "生成存案预览",
    "/reset": "[存案ID]  清空临时对话或回退有效栈",
    "/quit": "退出占案",
}


def line_names(mask):
    return "、".join(SLOTS[i] for i in range(1, 7) if mask & (1 << (i - 1))) or "无"


def item_text(item):
    return f"〔{TYPES[item['type']]}〕{item['content']}\n辞：{item.get('interpretation') or '无'}"


def items_text(items):
    return "\n".join(item_text(item) for item in items) or "暂无挂事"


def state_text(state, schema, *, all_slots=False):
    digits = state["digits"]
    base = derive(digits, {"kind": "base"})
    changing = derive(digits, {"kind": "changing"})
    summary = [f"易例：{schema['name']} {schema['version']}", f"所闻之事：{state['question']}",
               "数字卦：" + " ".join(map(str, digits)), f"本卦：{base['name']}",
               f"动爻：{line_names(moving_mask(digits))}", f"之卦：{changing['name']}"]
    if all_slots:
        summary.extend(f"{slot}\n{items_text(items)}" for slot, items in zip(SLOTS, state["bindings"]))
    return "\n".join(summary)


def delta_text(delta):
    blocks = []
    if change := delta.get("question"):
        blocks.append(f"所闻之事\n原：{change['before']}\n新：{change['after']}")
    for index, slot in enumerate(SLOTS):
        changes = []
        for change in delta["items"]:
            if change.get("slot", change.get("from")) != index:
                continue
            kind = change["kind"]
            if kind == "add":
                changes.append("新增 " + item_text(change["after"]))
            elif kind == "remove":
                changes.append("删除 " + item_text(change["before"]))
            else:
                heading = "修改" if kind == "update" else f"移挂 {slot} → {SLOTS[change['to']]}"
                changes.append(f"{heading}\n原：{item_text(change['before'])}\n新：{item_text(change['after'])}")
        if changes:
            blocks.append(slot + "\n" + "\n".join(changes))
    return "\n\n".join(blocks)


def view_text(derived):
    mapping = "、".join(f"{line}←{source}" for line, source in enumerate(derived["source_lines"], 1))
    return (f"{view_label(derived['view'])} · {derived['name']}\n"
            f"变化爻：{line_names(derived['mask'])}\n来源映射：{mapping}")
