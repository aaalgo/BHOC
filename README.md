# BHOC

BHOC（Boolean Hypercube Oracular Calculus）是一个中文终端应用，用周易卦象组织问题、证据、假设和备选行动。一次占案固定一个本卦，挂事可放在卦上或六个爻位。变卦提供不同的观察视角，事实和预测需要独立证据检验。

## 快速开始

需要 Python 3.11 或更新版本，以及 Linux 或 macOS 终端。在项目目录运行以下命令。

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
bhoc resume examples/nvda.json
```

NVDA 示例包含已保存的正式存案，可直接查看卦象和挂事。程序会把续案保存到 `./bhoc-sessions/<新占案ID>.json`，原示例文件保持原样。

首次拟象、论卦和存案预览使用 OpenAI Responses API。启动前在环境中设置 `OPENAI_API_KEY`。如果同时设置了 `BHOC_API_KEY`，后者优先。

| 环境变量 | 用途 |
| --- | --- |
| `BHOC_MODEL` 或 `OPENAI_MODEL` | 主模型，默认 `gpt-6.2-astra` |
| `BHOC_TOOL_MODEL` | 首次拟象的 JSON 转换模型，默认 `gpt-6.1-terra` |
| `BHOC_BASE_URL` 或 `OPENAI_BASE_URL` | Responses API 的基地址，默认 `https://api.openai.com/v1` |

要从起卦开始，直接运行 `bhoc`。程序会把新占案保存到 `./bhoc-sessions/<占案ID>.json`。

## 从起卦到存案

1. 选择易例。内置通用、政治、金融、医疗和婚恋。
2. 输入所闻之事，可一并说明背景、需要核查的资料和分析约束。
3. 选择三钱起卦，或按初爻至上爻输入六个 6 至 9 的数字。例如 `7 8 8 6 9 9` 得本卦风雷益，四爻、五爻、上爻动，之卦震为雷。
4. 起卦完成后，主模型按需联网核查，逐条列出挂点、类型、内容、辞和来源。工具模型将条目转换成 JSON，Core 校验后自动保存首条正式存案。
5. 输入普通文字继续论卦。主模型读取当前存案、临时对话和所选视角，按需搜索新资料。执行 `/commit` 时，主模型直接生成完整状态 JSON，Core 校验并展示差异。输入 `/confirm` 保存，或输入 `/cancel` 保留当前存案与临时对话。

首条正式存案保存后，续案直接读取已保存的挂事、来源链接和临时对话，先前的搜索无需重跑。如果首次拟象失败或中断，文件仍保留起卦记录。续案时若只有起卦记录，程序会在新占案中重试首次拟象。

## 常用命令

| 输入 | 行为 |
| --- | --- |
| `/help` | 查看命令和参数 |
| `/state [存案ID]` | 查看当前或指定存案的七处挂事 |
| `/log [存案ID]` | 列出有效存案，或查看某条存案相对父案的差异 |
| `/view [视角]` | 查看或切换视角，例如 `/view 互卦` 或 `/view 变 2 5` |
| `/views` | 打开变卦选择窗 |
| `/commit` | 预览本轮状态变更 |
| `/reset [存案ID]` | 清空临时对话，或在确认后回退到指定存案 |
| `/quit` | 退出并保留已保存的临时对话 |

按 `F6` 切换论卦栏和卦象栏。在卦象栏用左右方向键选列，按 `0` 查看卦上挂事，按 `1` 至 `6` 查看各爻，按 `V` 选择变卦。聊天输入框支持 `Tab` 补全命令和上下方向键查看输入历史。

## 本地易例与开发

可在启动目录的 `schemas/` 添加易例。参考 [内置易例](bhoc/schemas)，在 Markdown 文件开头用 `---` 包围 `id`、`version` 和 `name` 三个字段，随后填写正文。占案保存选定版本及正文，续案时继续沿用。

运行自动化测试使用以下命令。

```sh
python -m unittest discover -s tests -v
```

- [CLI.md](CLI.md) 说明界面、命令和占案文件。
- [BHOC-CORE.md](BHOC-CORE.md) 定义状态、卦象计算和存案操作。
- [BHOC-CALCULUS.md](BHOC-CALCULUS.md) 定义拟象、挂事与通变协议。
