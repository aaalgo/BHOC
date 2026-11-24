"""Deterministic hexagram calculations and state validation."""
import json
import secrets
from pathlib import Path

DATA = Path(__file__).parent
SLOTS = ("卦上", "初爻", "二爻", "三爻", "四爻", "五爻", "上爻")
TYPES = {"fact": "事实", "hypothesis": "假设", "decision": "决策", "prediction": "预测"}
VIEWS = {"base": "本卦", "changing": "之卦", "nuclear": "互卦",
         "complement": "错卦", "reverse": "综卦", "change": "变"}
# Rows are upper trigrams and columns lower trigrams, encoded from the bottom.
NAMES = (
    "坤为地 地雷复 地水师 地泽临 地山谦 地火明夷 地风升 地天泰",
    "雷地豫 震为雷 雷水解 雷泽归妹 雷山小过 雷火丰 雷风恒 雷天大壮",
    "水地比 水雷屯 坎为水 水泽节 水山蹇 水火既济 水风井 水天需",
    "泽地萃 泽雷随 泽水困 兑为泽 泽山咸 泽火革 泽风大过 泽天夬",
    "山地剥 山雷颐 山水蒙 山泽损 艮为山 山火贲 山风蛊 山天大畜",
    "火地晋 火雷噬嗑 火水未济 火泽睽 火山旅 离为火 火风鼎 火天大有",
    "风地观 风雷益 风水涣 风泽中孚 风山渐 风火家人 巽为风 风天小畜",
    "天地否 天雷无妄 天水讼 天泽履 天山遁 天火同人 天风姤 乾为天",
)
NAMES = " ".join(NAMES).split()
TRIGRAMS = "坤震坎兑艮离巽乾"
class BHOCError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise BHOCError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def fields(value, expected, label, optional=()):
    require(isinstance(value, dict) and set(expected) <= value.keys()
            and value.keys() <= set(expected) | set(optional), f"{label}的字段无效")


def validate_digits(digits):
    require(isinstance(digits, list) and len(digits) == 6
            and all(type(digit) is int and 6 <= digit <= 9 for digit in digits),
            "请输入初爻至上爻的六个 6 至 9 的整数")


def cast_coins():
    return [sum(2 + secrets.randbelow(2) for _ in range(3)) for _ in range(6)]


def validate_state(state, original=None):
    fields(state, ("question", "schema", "digits", "bindings"), "状态")
    require(nonempty(state["question"]), "所闻之事不能为空")
    schema = state["schema"]
    fields(schema, ("id", "version"), "易例引用")
    require(all(map(nonempty, schema.values())), "易例标识和版本必须为非空文字")
    validate_digits(state["digits"])
    if original is not None:
        require(all(state[key] == original[key] for key in ("schema", "digits")),
                "数字卦和易例版本必须沿用起卦设置")
    bindings = state["bindings"]
    require(isinstance(bindings, list) and len(bindings) == 7, "状态须包含七处挂点")
    seen = set()
    for slot in bindings:
        require(isinstance(slot, list), "挂点须为列表")
        for item in slot:
            fields(item, ("id", "type", "content"), "事", ("interpretation",))
            require(nonempty(item["id"]) and item["id"] not in seen, "事的标识须非空且唯一")
            require(isinstance(item["type"], str) and item["type"] in TYPES, "事的类型无效")
            require(nonempty(item["content"]), "事的内容不能为空")
            require(isinstance(item.get("interpretation", ""), str), "辞须为文字")
            seen.add(item["id"])


def validate_view(view):
    fields(view, ("kind",), "视角", ("mask",))
    kind = view["kind"]
    require(isinstance(kind, str) and kind in VIEWS, "视角无效")
    if kind == "change":
        require(type(view.get("mask")) is int and 0 <= view["mask"] < 64, "爻变掩码无效")
    else:
        require("mask" not in view, "此视角无须爻变掩码")


def moving_mask(digits):
    return sum(1 << index for index, digit in enumerate(digits) if digit in (6, 9))


def derive(digits, view):
    validate_view(view)
    kind = view["kind"]
    base = [digit % 2 for digit in digits]
    sources = list(range(1, 7))
    mask = 0
    if kind == "nuclear":
        sources = [2, 3, 4, 3, 4, 5]
    elif kind == "reverse":
        sources.reverse()
    elif kind == "changing":
        mask = moving_mask(digits)
    elif kind == "complement":
        mask = 63
    elif kind == "change":
        mask = view["mask"]
    bits = [base[source - 1] ^ ((mask >> index) & 1) for index, source in enumerate(sources)]
    code = sum(bit << index for index, bit in enumerate(bits))
    return {"view": view, "bits": bits, "name": NAMES[code], "source_lines": sources,
            "mask": sum(1 << i for i in range(6) if bits[i] != base[i])}


def view_label(view):
    label = VIEWS[view["kind"]]
    if view["kind"] == "change":
        label += " " + " ".join(str(i + 1) for i in range(6) if view["mask"] & (1 << i))
    return label


def list_views(digits):
    return [derive(digits, {"kind": "change", "mask": mask})
            for mask in sorted(range(64), key=lambda mask: (mask.bit_count(), mask))]


def base_structure(digits):
    base = derive(digits, {"kind": "base"})
    bits = base["bits"]
    lower = sum(bits[i] << i for i in range(3))
    upper = sum(bits[i + 3] << i for i in range(3))
    lines = []
    for index, (bit, digit) in enumerate(zip(bits, digits), 1):
        opposite = (index + 2) % 6 + 1
        adjacent = [line for line in (index - 1, index + 1) if 1 <= line <= 6]
        lines.append({"爻位": index, "阴阳": "阳" if bit else "阴", "动": digit in (6, 9),
                      "居中": index in (2, 5), "当位": bit == index % 2,
                      "承上": index + 1 if index < 6 else None,
                      "乘下": index - 1 if index > 1 else None, "相比": adjacent,
                      "相应位置": opposite, "应位阴阳相异": bit != bits[opposite - 1]})
    return {"本卦": base, "上卦": TRIGRAMS[upper], "下卦": TRIGRAMS[lower],
            "爻": lines}


def diff(before, after):
    validate_state(after, before)
    old = {item["id"]: (slot, item) for slot, items in enumerate(before["bindings"]) for item in items}
    new = {item["id"]: (slot, item) for slot, items in enumerate(after["bindings"]) for item in items}
    delta = {"items": []}
    if before["question"] != after["question"]:
        delta["question"] = {"before": before["question"], "after": after["question"]}
    for item_id in dict.fromkeys((*old, *new)):
        if item_id not in old:
            slot, item = new[item_id]
            change = {"kind": "add", "slot": slot, "after": item}
        elif item_id not in new:
            slot, item = old[item_id]
            change = {"kind": "remove", "slot": slot, "before": item}
        else:
            start, prior = old[item_id]
            end, current = new[item_id]
            if start != end:
                change = {"kind": "move", "from": start, "to": end, "before": prior, "after": current}
            elif prior != current:
                change = {"kind": "update", "slot": start, "before": prior, "after": current}
            else:
                continue
        delta["items"].append(change)
    return delta


def parse_json(text):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"JSON 字段重复：{key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise BHOCError(f"JSON 数值无效：{value}")

    try:
        return json.loads(text, object_pairs_hook=object_pairs, parse_constant=invalid_constant)
    except (json.JSONDecodeError, RecursionError) as error:
        raise BHOCError("JSON 格式无效") from error
