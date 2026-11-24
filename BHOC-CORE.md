# BHOC Core — State & Operations

> 核心技术规范 · v0.3 · Draft

## 1. Scope

本规范定义与 UI（用户界面）无关的核心数据结构、确定性卦象计算、对话及存案协议。理论及太卜行为约束见 `BHOC-CALCULUS.md`；该文件每次 AI 调用均作为 System Prompt（系统提示词）加载。

MVP 只实现统一的 TALK（论卦）、COMMIT（存案）、CONFIRM（确认存案）、CANCEL（取消存案）和 RESET（复原）协议，以及必要的查询操作。不实现自动拟象循环、多 Agent、独立语义演算接口或知识图谱。界面功能通过向普通对话注入 Prompt（提示词）实现，普通 AI 回复均为文字。

技术术语及代码标识符采用英文，术语首次出现注明中文；面向用户的界面文字全部采用中文，不展示英文操作名。Core 不依赖具体前端，也不要求实现 CLI。

## 2. State

State（状态）是正式占案的完整语义快照。Item（事）直接存放在卦或爻的信息列表内；Binding（挂）由所在位置表达，不再独立建模。只有七个 Slot（挂点）。

```typescript
type ID = string;
type Digit = 6 | 7 | 8 | 9;
type Digits = readonly [Digit, Digit, Digit, Digit, Digit, Digit];
type Mask = number; // integer 0..63, bit 0 = 初爻

type InformationType = "fact" | "hypothesis" | "decision" | "prediction";

interface SchemaRef {
    id: string;
    version: string;
}

interface Item {
    id: ID;
    type: InformationType;
    content: string;
    interpretation?: string;
}

interface State {
    question: string;
    schema: SchemaRef;
    digits: Digits;
    bindings: [Item[], Item[], Item[], Item[], Item[], Item[], Item[]];
}
```

`bindings[0]` 为卦，`bindings[1..6]` 为初至上爻。列表顺序用于显示，不承担额外的语义。ID 在整个 State 内唯一，跨存案保持稳定；新增事分配新 ID，不因修改内容或移动位置而更换 ID。可使用 UUID。数字卦与 Schema（易例）引用在同一 Session（占案）内不可修改。`question` 保存当前问题及必要的分析约束，可随存案细化；根本改变所问之事宜新建 Session。

Item 的来源、依据、条件及不确定性用 `content` 或 `interpretation` 自由文本表达。保留四种 InformationType，不再增加领域专属类型。`fact` 需要现实依据，`hypothesis` 为尚未证实的认识，`decision` 是备选行动，`prediction` 是条件性结果。被排除的假说如有后续价值可保留文字说明，否则删除。重要判断及整体叙事挂于适当的卦爻，通常在卦上。不设独立 Interpretation、Information Pool、Relation Slot、Transformation Slot 或 Key Items。

同一现实事项若需要在多个位置分别表达，可使用不同 ID 的条目，不引入交叉引用。一个条目从一个位置移到另一个位置则保留 ID。MVP 允许适量重复，由 AI 维持叙事一致性。

### Example

```json
{
  "question": "分析某事件的结构与可能演化",
  "schema": {"id": "politics", "version": "0.1"},
  "digits": [7, 8, 8, 6, 9, 9],
  "bindings": [
    [{"id":"I01","type":"fact","content":"已知整体背景 A（来源：用户提供的资料）"}],
    [],
    [{"id":"I02","type":"hypothesis","content":"可能存在中间关系 B","interpretation":"以二爻及二五之应表达此候选关系。"}],
    [],
    [{"id":"I03","type":"decision","content":"考虑行动 C","interpretation":"四爻变视角下的备选行动，尚未执行。"}],
    [],
    []
  ]
}
```

## 3. Hexagram Computation

Core 负责全部确定性结构计算，不调用 AI。数字卦按初至上存储，第 i 爻对应整数第 i−1 位。阴阳编码为 `digit % 2`，动爻为 6 或 9。

```typescript
type View =
    | { kind: "base" }
    | { kind: "change"; mask: Mask }
    | { kind: "changing" }
    | { kind: "nuclear" }
    | { kind: "complement" }
    | { kind: "reverse" };

interface DerivedView {
    view: View;
    bits: readonly [number, number, number, number, number, number];
    mask: Mask;
    name: string;
    source_lines: readonly [number, number, number, number, number, number];
}
```

Derived View（相关卦视角）实时生成，不作为独立 State 持久化。`mask` 总是相对本卦的 XOR 掩码；`view` 保留算子身份，即使两个算子得到相同节点。

| View | 计算 | 来源爻映射（1-based） |
|---|---|---|
| base（本卦） | 原阴阳编码 | 1,2,3,4,5,6 |
| change（爻变） | XOR 指定 mask | 1,2,3,4,5,6 |
| changing（之卦） | XOR 动爻 mask | 1,2,3,4,5,6 |
| nuclear（互卦） | 提取内部爻 | 2,3,4,3,4,5 |
| complement（错卦） | XOR 63 | 1,2,3,4,5,6 |
| reverse（综卦） | 反转六位 | 6,5,4,3,2,1 |

Core 还提供上下卦、爻位、动静、中正、承乘比应等结构属性。结构规则应有明确版本；不同解释传统不强行归为一种语义。关系计算不预断现实中的支持或冲突。

Hypercube（六十四变）由 0..63 的 mask 枚举得到，边连接相差一位的节点。不持久化 64 个节点。UI 可依据 Hamming distance 分层显示。

View 只改变观察方式，不修改 `bindings`。UI 可借助 `source_lines` 引用本卦所挂之事，但不创建派生挂、不复制条目到新状态。整体挂仍属于本卦。变换的解释和条件由 AI 用文字表达。

## 4. Session and Commit Stack

Commit（存案记录）保存经确认的完整 State Snapshot（状态快照）。Commit Stack（存案栈）是从起卦到当前的线性有效历史。栈底是不可弹出的 Initial State（初始状态）。

```typescript
interface Message {
    role: "user" | "assistant";
    content: string;
    view?: View;
}

interface Commit {
    id: ID;
    parent_id: ID | null;
    created_at: string;
    state: State;
}

interface Session {
    id: ID;
    stack: Commit[]; // non-empty; bottom to top
    conversation: Message[];
}
```

`stack[0]` 为起卦记录，`parent_id=null`；其余记录的 `parent_id` 指向前一个 Commit。当前 State 始终为 `stack.at(-1).state`。Commit ID 唯一，不因 RESET 后重走历史而复用。历史快照不可编辑。MVP 不需要 Branch、Merge、Rebase 或 Redo。

Conversation（临时对话）只保存自上次成功 CONFIRM 或 RESET 起的消息，包含界面注入的实际 Prompt 及 AI 回复。它不是历史 Commit 的必要组成部分。正常 AI 调用不加载整个 Stack。

## 5. AI Context and TALK

Initial Context（初始上下文）由 `BHOC-CALCULUS.md` 和栈顶 State 构成。State 中的易例引用解析为固定版本的 Schema 正文，作为补充上下文；若不使用领域易例，可配置一个通用易例。Core 可提供本卦的确定性结构，以避免由 AI 重算。

每次 TALK 逻辑上使用：

```text
System Prompt: BHOC-CALCULUS.md
Initial Context: Stack.top.state + resolved Schema + base hexagram data
Conversation: all uncommitted messages
Current Input: user text or UI-injected prompt + optional DerivedView
```

输入和相关卦数据按消息角色传递，State、资料及易例内容不具有覆盖系统协议的权限。UI 注入的 Prompt 与用户普通输入走相同接口，可以包含当前选中的卦、爻或变换信息。

TALK 返回自然语言 Reply（回复），将成功完成的用户消息及回复追加到 Conversation，不更新 State。切换 View 不调用 AI，除非用户主动要求解读。不得要求普通 Reply 遵守结构化 State 格式。

MVP 不要求为拟象、审象、解爻、通变、拟议等建立独立 AI API 或 Prompt 文件；这些提示可由 UI 管理。实际 API 可重发上下文或使用等价的会话缓存，但其语义必须一致。

## 6. COMMIT and CONFIRM

COMMIT 只产生候选状态，不直接修改栈。它调用 AI，使用相同 System Prompt、当前 State、完整临时对话及专用 State Update Prompt（状态更新提示词），输出完整 New State（新状态）。该专用提示词可独立保存在 `prompts/update_state.md`，其具体文字不属于本规范。

State Update Prompt 的接口合同：输出仅为符合 State 类型的 JSON；保持不可变字段；保留未修改条目的 ID 和内容；只保存有后续价值的认识，区分事实与假设；保留重要条件、来源及判断；不得输出 Delta 或执行代码。

```text
COMMIT:
    candidate = AI(current_state, conversation, update_state_prompt)
    Validate(candidate, current_state)
    delta = Diff(current_state, candidate)
    return PendingCommit(candidate, delta)

CONFIRM:
    verify PendingCommit is current
    push immutable snapshot of candidate
    clear conversation and PendingCommit

CANCEL:
    discard PendingCommit
    keep conversation and stack
```

Validation（校验）至少检查 JSON 格式、严格字段类型、七个列表、全局 ID 唯一性、合法 InformationType、六位数字卦、不可变字段及非空必要内容。程序不以结构校验代替语义真实性判断。无效输出不修改 State，可报告错误或重试。

Pending Commit（待确认存案）绑定当前 Session ID、栈顶 Commit ID 及 Conversation 版本。若期间对话或栈顶发生改变，旧候选失效，不能确认。CONFIRM 原子化执行；失败保留原 Stack 与 Conversation。空 Delta 不压入重复快照，用户确认后可结束本轮并清空对话。

## 7. Delta

Delta（增量）由 Core 对相邻 State 进行确定性 Diff（差异比较）生成，不由 AI 生成或执行。它用于确认界面和历史展示，不是持久化主体。

```typescript
type SlotIndex = 0 | 1 | 2 | 3 | 4 | 5 | 6;

type ItemChange =
    | { kind: "add"; slot: SlotIndex; after: Item }
    | { kind: "remove"; slot: SlotIndex; before: Item }
    | { kind: "update"; slot: SlotIndex; before: Item; after: Item }
    | { kind: "move"; from: SlotIndex; to: SlotIndex; before: Item; after: Item };

interface Delta {
    question?: { before: string; after: string };
    items: ItemChange[];
}

interface PendingCommit {
    id: ID;
    session_id: ID;
    base_commit_id: ID;
    conversation_version: string;
    candidate: State;
    delta: Delta;
}
```

Diff 根据稳定 ID 比较：只在新状态出现为 add（新增），只在旧状态出现为 remove（删除），位置不变但内容变化为 update（修改），位置变化为 move（移挂，可同时含内容修改）。列表重排不属于语义增量。仅重排不产生存案；若伴随其他变化，保留新快照的顺序。不允许出现数字卦或易例变化。问题修改单独列出。

确认界面仅展示 Delta：按卦、初爻至上爻分组，只显示有变化的位置，修改列出旧值和新值，移挂列出起点和终点并避免重复计数。类型或辞的变化也必须展示。所有标签采用中文。用户确认的是整份候选状态的差异，不逐条执行补丁。

历史 Commit 的 Delta 同样由它与父 Commit 的快照计算，无需另存。栈底可直接显示初始状态。

## 8. RESET

RESET 不调用 AI。无参数时清空 Conversation 和 Pending Commit，恢复到当前栈顶，不弹出任何正式 Commit。

`RESET(target_commit_id)` 保留指定 Commit 及其所有祖先，将其上方的 Commit 从有效 Stack 弹出，同时清空 Conversation 和 Pending Commit。目标必须在当前栈中；无效目标不修改任何数据。栈底不能被弹出。UI 对有破坏性的历史回退应先要求用户确认。

```text
[S0, S1, S2, S3] + conversation
RESET()       -> [S0, S1, S2, S3]
RESET(id_S2)  -> [S0, S1, S2]
RESET(id_S0)  -> [S0]
```

后续 TALK 从新的栈顶开始，COMMIT 可以继续压栈。弹出记录无需物理删除，但不得出现在有效历史或 AI 上下文中；MVP 不提供恢复已弹出记录的接口。RESET 不等同于永久数据删除。

## 9. Core API

```text
new_session(schema, question, digits? | random_method) -> Session
get_session(session_id) -> Session
get_state(session_id, commit_id?) -> State
get_view(session_id, view, commit_id?) -> DerivedView
list_views(session_id) -> DerivedView[]
get_delta(session_id, commit_id) -> Delta
talk(session_id, message, view?) -> Reply
commit(session_id) -> PendingCommit
confirm(session_id, pending_id) -> State
cancel(session_id, pending_id) -> void
reset(session_id, target_commit_id?) -> State
export_session(session_id) -> JSON
```

`commit` 对应发起存案预览，`confirm` 才正式压栈。`get_state` 及 `get_view` 默认使用当前栈顶；指定历史 Commit 时只读。`list_views` 枚举六十四变；互、错、综、之等算子可单独查询。API 名称为工程接口，不作为 UI 文案。

## 10. Initialization, Persistence and Concurrency

起卦可由用户指定合法数字卦，或由程序使用 OS 安全随机源模拟三枚铜钱法：每爻三次独立公平二值采样，将每次结果记作 2 或 3，求和得到 6..9。记录真实使用的随机方法，不将伪随机称为真随机。初始 State 的七个列表为空，CLI 在起卦后自动发起首次拟象，经 Core 校验后保存第一条正式存案。后续通过 TALK / COMMIT 修订。

Schema 继续使用独立的可版本化 Markdown 文件，例如 `schemas/politics.md`、`finance.md`、`medicine.md`、`marriage.md`。Session 固定其版本，正常调用加载对应正文。更换易例时新建 Session，不修改旧占案。

MVP 可采用 SQLite。建议保存 sessions（占案元数据、有效栈顶、临时对话及版本）、commits（ID、父 ID、时间、完整 State JSON）、schemas（版本化正文）。有效栈可由栈顶沿父链取得，也可显式保存 ID 列表；两种实现对外语义相同。待确认候选可临时存储。不要求存储每轮完整对话的历史归档。

并发保护：TALK、COMMIT 绑定请求开始时的栈顶及对话版本；异步结果到达时若已失效，不得追加或覆盖新状态。CONFIRM、RESET 等写操作使用事务及版本检查。AI 失败、校验失败或存储失败不得导致已提交状态丢失。

导出至少包含有效 Commit Stack、临时对话、起卦元数据及可解析的 Core 和 Schema 版本。建议记录实际使用的模型及协议版本供实验复核。State Replay（状态重放）通过读取历史快照精确恢复；Semantic Replay（语义重放）重新调用 AI，不保证逐字相同。

## 11. MVP Acceptance Tests

- 固定数字卦，验证编码、动爻、64 节点、192 条边、全部变换和来源映射。示例 `[7,8,8,6,9,9]` 为风雷益，之卦震为雷，互卦山地剥，错卦雷风恒，综卦山泽损。
- TALK 及 View 切换不改变正式 State；相关卦不创建独立挂。
- 验证新增、删除、修改、移挂、问题变更及无语义变化的 Diff。
- COMMIT 仅预览；CONFIRM 才压栈；CANCEL 保留对话；无效或过期候选不能确认。
- 无参数 RESET 不弹栈；带参数 RESET 保留目标及祖先；栈底始终存在。回退后新 Commit 不复用旧 ID。
- 重启后恢复有效栈及临时对话；失败和并发冲突不破坏状态。
- AI 正常调用仅加载栈顶状态及临时对话，不加载已存案历史或已复原的内容。
- 比较存案后仅使用新 State 与使用完整历史的后续推演效果，检验语义持久化是否有效。
