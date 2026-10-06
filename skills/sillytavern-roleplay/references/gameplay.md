# 剧本自带玩法 · 引擎 5.0

剧本由世界观、设定集、可选的世界玩法与素材构成。世界玩法携带实际规则代码，主程序提供通用加载器、JSON 调用协议、存档和受限的世界状态接口。模块 ID 无需提前注册：委托、战斗、推理、经营可以在不同剧本里自行实现。当前运行时为 `python-restricted-v1`，不是任意 Python 包或任意网页应用运行器。

## 创建一个完整剧本

使用脚本绝对路径、明确的资料库和空的输出文件夹。以下命令中的占位符需要替换为实际绝对路径：

```powershell
python "<技能目录>/scripts/create_script.py" "<新剧本文件夹>" --id my-story --name "我的故事"
python "<技能目录>/scripts/worlds.py" --root "<资料库>" validate-script "<新剧本文件夹>"
python "<技能目录>/scripts/worlds.py" --root "<资料库>" import-script "<新剧本文件夹>"
```

创建命令只写入一个完整、可编辑的原创示例，不导入、不启动、不覆盖非空目录。随后修改 `world.json` 的背景、名称、开场，修改 `settings.json` 的人物、地点、规则等资料。角色卡的 description/personality 是模型资料；人物卡的面向玩家简介字段遵循 [browser.md](browser.md) 的人物卡规则，不写入模型判断或存档内部机制。没有世界玩法的旧 JSON 剧本仍可直接导入。

已有可运行的目录包见 `assets/world-templates/module-package-example/`；独立 JSON 例子为 `gameplay-training-script.json`，包含战斗模块。春物默认包 `oregairu-script.json` 包含剧本自带的侍奉部委托簿。训练示例是开发用的独立剧本，不导入春物世界。

```text
my-story/
  manifest.json
  world.json
  settings.json
  world-gameplay/
    rules.module.json
    rules.py
```

`manifest.json`：

```json
{"spec":"yukima_script_v1","world":"world.json","setting_sets":["settings.json"],"world_gameplay":["world-gameplay/rules.module.json"]}
```

所有文件引用（包括模块 code_file）均相对于根 manifest，不相对于模块子文件夹。禁止跨出包目录、绝对外部路径和缺失文件。JSON 单文件包可以直接写 `world` 对象、`setting_sets` 数组，并在 `world_gameplay` 模块中内嵌 `source` 字符串。`world.world_gameplay` 是导入后生成的固定版本引用，作者不要手填哈希。

世界观必填：稳定 `id`、`name`、`background`、存在的 `setting_set_ids`、`primary_card_id`；开场写在 `opening_scenes` 中，包含稳定 id、title、description、background、scene、opening 分镜和 choices。设定卡类型：character/location/item/rule/event，使用稳定 id、name、description，可包含 aliases、appearance 和 character_card。人物交互按各自性格、知识、距离与真实关系，不能用“玩法成功”强迫感情或出场。

可选世界字段：

```json
{"calendar":{"date":"2026-04-06","minute":960},"initial_items":{"player-notebook":{"id":"player-notebook","name":"笔记本","owner":"player","quantity":1,"location":"书包"}}}
```

date 可以省略，此时用故事第几天；minute 为 0–1439。设定人物可写 `initial_relation`，按主角 ID 区分 trust/familiarity（0–100）与 identity；独立于 initial_affinity。`schedule_tendencies` 是简短的日程倾向，影响合理的场所和遇见机会，不是强制日程表。年龄、玩家简介、初始好感必须由作者根据故事起点设定，不将新资料自动倒灌进既有存档。

## 模块描述与代码

`world-gameplay/rules.module.json`：

```json
{"id":"my-rules","name":"探索记录","version":"1.0.0","api_version":1,"runtime":"python-restricted-v1","code_file":"world-gameplay/rules.py","config":{},"capabilities":[],"dependencies":{}}
```

dependency 为模块 ID 到准确 version 的字典，导入检查缺失、版本和循环，按依赖顺序运行。依赖状态以只读 JSON 副本提供在 request.context.modules 中。当前每剧本最多12模块，代码64KiB/模块，单次输入512KiB、输出128KiB；子进程最多3秒、10万行执行和128MiB内存。禁止 import、类、文件、网络、系统命令、反射和私有属性；可以使用普通函数、分支、循环、算术、列表/字典与受支持的字符串方法。可用内置函数以 gameplay_worker.py 的白名单为准。它提供纯计算隔离和资源限制，不能宣称是支持不可信任任意代码的操作系统沙箱。

每个代码文件定义 `run(request)`，接收：

- mode：initialize / view / context / event。
- state：该模块的独立 JSON 状态，initialize 时为空；代码不得依赖跨调用全局变量。
- config：剧本模块配置。
- context：当前已确认的 calendar/items/relations/threads、scene、人物 ID/姓名、turn_id、稳定 roll、声明依赖的 modules。
- event：event 模式时包含 action_id、input、真实对白/旁白 frames；没有人物心声。

返回对象至少包含 `state` 对象、`effects` 数组。view/context 必须原样返回 state 且 effects=[]，查看界面绝不结算。initialize 初始化状态；event 根据当前状态判断动作是否合法，非法时返回 `rejected` 中文原因，有效时可返回 `outcome` 供叙事如实描写。

一个不要求主程序新增规则的完整最小模块：

```python
def run(r):
    s = r['state']
    if r['mode'] == 'initialize':
        s = {'visited': 0}
    if r['mode'] == 'event':
        if r['event'].get('action_id') != 'look':
            return {'state': s, 'effects': [], 'rejected': '目前无法这样探索。'}
        s['visited'] += 1
    return {
        'state': s, 'effects': [],
        'outcome': '完成了一次观察。',
        'view': {
            'cards': [{'title': '探索记录', 'text': '观察次数：' + str(s['visited']), 'status': ''}],
            'actions': [{'id': 'look', 'label': '观察四周', 'text': '【动作】仔细观察当前场所。'}]
        },
        'context': {'rules': '观察后只描写当前场所能看到的东西，不凭空制造奖励。', 'progress': s}
    }
```

view.cards 可包含 title/text/status/details；view.actions 必须包含稳定 id、label、带【语言】/【动作】/【环境】前缀的 text。模块代码动态决定哪些动作可用；主程序统一渲染卡片、记录和操作按钮，不理解具体战斗或委托规则。当前不执行剧本自带的任意 HTML/JavaScript UI。

context 可以返回隐式规则与进展；可选 `natural_actions`（格式同 actions）允许模型将实际对话识别为玩法事件。它不会自动创建按钮，适用于“本轮真实对白记录”“明确确认任务完成”等需要本轮观察结果的动作。模型只能提议允许列表中的 action_id，evidence 必须来自本轮玩家输入或可观察分镜，模块再检查具体前置条件。自然语言判断仍可能误判，关键资源与胜负应使用可验证的结构条件和显式动作，不能仅靠模型宣称成功。

## 通用世界状态接口

模块 `capabilities` 显式声明以下类型。effects 中每项必须带 type 和基于实际事件的 reason。全部在工作副本结算，只有文本回应及感知检查成功且存档 revision 未冲突，才与剧情一次提交。

| type | 主要字段 | 校验 |
|---|---|---|
| time | minutes，可选 date/minute | 非负经过时间，日期/时刻合法；旧档未设定时间时先设置 |
| items | id/name/owner/delta/location | 稳定物品ID，同一持有者，数量不能负；转移扣原ID，再新增接收者的ID |
| relations | actor_id/trust/familiarity/identity | 真实人物、变化范围与依据；剧情提议只影响真正互动者，亲密身份须明确双方共识 |
| threads | id/title/status/note/deadline | 稳定事件ID，open/active/resolved/cancelled；尚不存在的事件不能直接结束 |

涉及同一资源的多个效果必须由模块按顺序给出，任何一项失败整轮不提交。随机值 roll 来自 turn_id，重试不重掷。模块已结算时长时，本轮文本不会再次扣同一个动作的时间。模型也不能再次结算同一玩法按钮。

## 导入、更新与存档

`validate-script` 在临时目录检查整包：角色卡、开场、ID、引用、模块版本、依赖、代码、初始化及界面，不改变目录库。校验成功后再 `import-script`；提交目录库时保留原内容供写入错误回滚。角色卡同 ID 不同内容仍拒绝，需另选 ID；设定集、世界观和玩法新版本可更新目录，旧存档保留快照。

模块的完整定义按 script/module/sha256 存于资料库 `gameplay-modules`；存档中的 world_snapshot 固定对应版本，状态在 facts.browser_engine.modules。更新模块版本或代码不会静默改变旧剧情。旧档可从“手记”选择“在新分支中启用新版玩法”；原档保留，升级之前的回溯节点继续使用原版本。不要删除历史代码目录，否则旧档缺少其所需代码。

资料库另有 memory/<存档ID>（不可变整理结果）、browser/checkpoints/<存档ID>、recycle-bin 与 save-tombstones。所有模块、时间、物品、关系、事件与记忆按各自分支保存。记忆摘要只继承精确匹配的历史前缀，不能继承回溯点之后或同胞分支的内容。后台摘要失败使用原文摘录，原始 turn 与观察记录始终保留；摘要给叙事引擎使用，人物获知的事情仍按该人物的观察分别检索。

存档管理支持名称、备注、搜索、只回收本档或整棵分支、恢复、ZIP导入导出。主界面与游戏菜单共用存档管理，外层每条故事只列起始父档，按整条故事最近保存时间排序；搜索任意子档名称、备注或简介时保留完整故事分组。进入故事后关闭原弹窗并隐藏原页面，显示独立横向分支页；各档从左向右按真实父子关系连线，不限制子档数量。拖动空白处、底部滑条、方向键或“定位最近存档”浏览长故事，“退出分支图”或 Escape 返回来源页面。点击任意节点按其准确 ID 读取；节点的“管理”可改名、导出或回收。缺失父档的分支仍显示，同一 root_id 的孤立分支共用页面，不伪造连接。游戏内的当前持久存档受保护；返回主界面后可回收，服务先卸载它并建立未保存的开场，防止后台重新创建已删除的存档。删除父档不改变子档的父编号；恢复后来源关系保留。存档包不包含API密钥、环境变量、服务配置或生成图片；生成图片需单独迁移对应素材库。文本故事导出仍从回看/脉络/心声进入，保持各人物对白完整。

实现和测试要使用隔离资料库，不在玩家存档里模拟剧情，不发布私有资料库或复制本机加密密钥。修改已安装技能和目录库时先保存文件备份，空闲时更新服务，恢复明确选定的原存档；不得因测试或维护启动一个新故事并冒充原进度。
