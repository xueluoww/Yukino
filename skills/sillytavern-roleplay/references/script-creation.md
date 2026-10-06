> 本公共版本使用项目内资料库；首次运行 launch.py 后建立。预装春物完整设定包与八幡主角，另附《雨后书屋》原创教程示例和旅人主角；不附带官方人物美术或私人存档。

# 创建与导入剧本（yukima_script_v1）

本文适用于 Yukino 0.8 项目内的 `sillytavern-roleplay` 技能及 `yukima_script_v1` 剧本格式。最方便的方式是在任意 Codex 聊天中引用你选定位置的技能，让 Codex 根据你的描述整理并导入；网页用于选择和游玩剧本，不提供上传入口。

## 剧本与主程序分开

壳提供通用运行接口；剧本由世界观、设定集、可选 world_gameplay 和素材构成。玩法可携带自己的代码，不需要在主程序里预先实现具体规则。目录结构、创建命令、模块协议与旧档升级见 [剧本与壳](../../../docs/剧本与壳.md)；纯文字剧本继续使用以下 JSON 教程。

## 1. 先弄清这几个对象

| 对象 | 放什么 | 存储位置 |
| --- | --- | --- |
| 世界观 `world` | 整个故事的时代、地点、常识、基调、初始处境及可选开场 | `<root>/worlds/` |
| 设定集 `setting_sets` | 人物、地点、物品、规则和事件卡；一个世界可引用多个设定集 | `<root>/setting-sets/` |
| 人物卡 | 人物经历、性格、说话方式、判断与边界；可内嵌在设定集，也可引用已导入卡 | `<root>/cards/` |
| 主角卡 | 玩家外貌参考；与供 AI 扮演的其他人物分开 | `<root>/protagonists/` |
| 视觉配置 | 人物立绘、表情、头像、场景键和图片路径 | `<root>/browser/characters.json` |
| 存档 | 某次游玩的对白、事实、记忆、关系、好感和节点快照 | `<root>/sessions/` 与 `browser/checkpoints/` |

一个可选剧本需要世界观、有效的人物资料锚点、所引用的设定集和至少一个开场。人物很多也只占一个剧本入口。设定是故事的资料，存档是玩家实际经历过的故事，两者分开。

`primary_card_id` 是文本引擎的资料锚点，不是玩家卡，也不意味着其他人物都由它代替。可以选择一个主要人物；无固定主要人物的剧本可明确创建叙事主持卡。群像人物来自设定集，各用自己的姓名、卡片和图像。

## 2. 在 Codex 聊天里创建，推荐用法

在新聊天引用你要使用的 `sillytavern-roleplay/SKILL.md`。本公共项目只使用项目内 database/roleplay-library；先运行 launch.py --demo 初始化，不自动读取其他安装位置的资料库。给出这样的请求即可：

> 使用已引用的角色扮演技能，在选定资料库中创建一个原创剧本《雨后书屋》。背景是现代海边小镇，故事从周六傍晚的旧书店开始。主要人物是店员林灯，温和、观察细致，不轻易答应不合理的请求；另有邻居阿澈，直率但不鲁莽。主角外貌先用原创旅人卡。请创建人物卡、玩家可读简介、地点和规则卡，准备两个可选开场，导入并检查能否出现在剧本选择页。只完成创建和导入，先不开始游戏。

你也可以提供人物 PNG/JSON 角色卡、已有设定文本或明确资料链接，说明哪些内容必须沿用，哪些可以原创。至少交代故事背景、主要人物和开始处境；年龄、外貌、旧关系等不确定内容可留空，不能补成已确认事实。

Codex 应完成：整理 UTF-8 剧本包 → 在临时资料库试导入 → 核对人物、开场与图鉴文案 → 按实际需要登记素材 → 导入选定资料库 → 检查目录。导入结束后由你在网页选择新剧本，不替换正在玩的存档。

## 3. 手动编辑剧本包

可直接复制技能内 `assets/world-templates/rainy-bookshop-script.json`（0.8 公共项目也提供 `examples/rainy-bookshop.json`），改 ID、标题、人设和开场。它是一个完整的原创示例，包含两个人物、地点、物品、规则和事件卡，以及两个开场；人物内嵌角色卡，所以不需要事先安装这些人物。

最外层必须包含：

```json
{
  "spec": "yukima_script_v1",
  "world": {},
  "setting_sets": []
}
```

### 世界观字段

| 字段 | 写法与作用 |
| --- | --- |
| `id` | 稳定且独立的剧本 ID，例如 `rainy-bookshop` |
| `name` | 玩家看到的剧本名称 |
| `description` | 选择页简介；自然介绍背景和玩法处境，不写引擎指令 |
| `background` | 模型读取的完整背景、常识、时间和因果约束；不要写玩家尚未经历的剧情为事实 |
| `primary_card_id` | 已有角色卡 ID，或本包内嵌人物的 `card_id` |
| `setting_set_ids` | 要引用的设定集 ID，须与本包或库中实际设定集一致 |
| `default_protagonist_id` | 默认主角卡 ID；省略时使用 `hachiman`；原创示例显式选择 `visitor` |
| `opening_scenes` | 可选开始场景，建议至少一个，最多 20 个 |

程序的 ID 只接受 1–80 个英文字母、数字、`-` 或 `_`；不要把中文标题直接当 ID。

### 设定集与人物卡字段

设定集包含 `id`、`name`、可选 `description` 和 `cards` 数组；每个设定集最多 200 张卡，同一集内的卡片 ID 不能重复。

卡片共用 `id`、`kind`、`name`、`description` 和可选 `aliases`。`kind` 可为：

| kind | 内容 |
| --- | --- |
| `character` | 人物资料与外貌 |
| `location` | 地点、空间布局和到达条件 |
| `item` | 物品、来源和使用条件 |
| `rule` | 常识、世界规律、叙事与行为边界；模型每轮读取规则卡 |
| `event` | 可能出现的事件及前提；不是保证会发生的预定结局 |

人物可以只提供基本设定，也可以完整内嵌酒馆角色卡：

```json
{
  "id": "lin-deng",
  "kind": "character",
  "name": "林灯",
  "aliases": ["店员", "林同学"],
  "card_id": "rainy-bookshop-lin-deng",
  "age": 22,
  "short_personality": "温和细致，认真而有主见。",
  "biography": "旧书屋的年轻店员，熟悉镇上的旧书和来往客人。",
  "personality": "温和、细心，有自己的判断。",
  "description": "处理委托前会确认事情的缘由。",
  "appearance": "年轻女性，深棕短发、琥珀色眼睛，米色针织衫和深色围裙。",
  "character_card": {
    "name": "林灯",
    "description": "旧书屋店员。年轻女性，深棕短发、琥珀色眼睛，米色针织衫和深色围裙。",
    "personality": "温和而有主见。愿意帮助别人，但涉及隐私、财物或不合理要求时会先询问、保留或拒绝。关系随真实经历发展。",
    "scenario": "现代海边小镇的一间旧书店。",
    "first_mes": "欢迎。你是来找书，还是避一会儿雨？"
  }
}
```

`character_card` 可使用 V1/V2/V3 酒馆 JSON。示例采用最容易编辑的 V1。导入后内嵌卡登记为独立人物卡，设定集通过 `card_id` 引用。引用已有卡时只写 `card_id`，不必再嵌入 `character_card`。

新剧本最好给所有新对象使用自己的 ID 前缀。同一人物卡 ID 已有不同内容时，导入会拒绝覆盖：改用新的 `card_id` 并同步修改锚点/引用。同一世界或设定集 ID 再导入则会更新其目录资料，所以不要无意复用其他剧本的 ID。

### 玩家简介与 AI 资料分别写

`biography`、`short_personality`、人物设定卡的 `personality` 是玩家在图鉴看到的介绍，只写身份、背景、性格和外貌。不要写“熟悉程度依赖存档”“不替玩家行动”等模型规则。

给 AI 的详细人设和判断规则放入 `character_card.description/personality`、世界观背景及 `rule` 卡。独立酒馆卡可用 `data.extensions.display_profile` 设置 `biography`、`summary`、`personality`、`appearance`、`age`、`avatar` 等玩家展示字段。未知年龄显示“未设定”。

人物的拒绝、接受、亲疏变化要符合本人性格和请求的合理性。好感不能改变核心人格，不能充当强迫同意或恋爱的开关。导入的是人物资料，不是当前周目的好感或记忆。

### 开始场景字段

每个 `opening_scenes` 条目含：

- `id`、`title`、`description`：场景 ID、选择页标题和简介。
- `scene`：初始时间与地点，例如“周六傍晚 · 旧书屋门口”。
- `background`：视觉配置中的稳定背景键，例如 `bookshop-rain`。
- `opening`：1–12 个分镜，每帧包含 `kind`、`speaker`、`text`、`expression`。
- `choices`：最多 3 条建议，每条有 `label` 和 `text`；可以为空。

`kind` 为 `dialogue`（对白）、`narration`（旁白）或 `thought`（人物心声）。对白的 `speaker` 使用人物姓名或已登记别名；旁白用空字符串。不要替玩家写台词、行动和内心，开场只建立处境与其他人物的回应。

`expression` 可使用：`neutral`、`soft`、`serious`、`shy`、`thinking`、`listening`、`troubled`、`surprised`、`sad`、`displeased`、`happy`、`eyes_closed`、`absent`。主要人物可备齐常用状态，配角至少备好平静、温和、认真和思考；`absent` 表示离场。

推荐内容和玩家正常输入相同，例如：

```json
{"label":"询问书店","text":"【语言】这里可以查旧书的来源吗？【动作】在柜台前停下。"}
```

点击建议只填入输入框，玩家确认后才发送。【语言】是发声，【动作】是行为，【环境】是场景设定，【内心】是没有说出口的想法；四者可以组合。是否被某人听到仍取决于在场、距离和接收对象。

## 4. 人物与背景图片怎样接进来

仅导入剧本 JSON 不会自动下载所有人物的图片，也不会无限生成整套表情。公共壳已为原创示例准备简易 SVG 人物与场景；春物有文字身份标签和几何背景，不附带官方角色图片。需要正式美术时可在 Codex 中要求准备或导入自己有权使用的素材。

本地素材接口支持 PNG/JPEG/WebP。把准备好的图片放在 `<root>/browser/assets/<自己的素材目录>/`。以人物 **实际 `card_id`** 为键，合并到 `<root>/browser/characters.json`，保留其他人物配置。例如：

```json
{
  "rainy-bookshop-lin-deng": {
    "name": "林灯",
    "aliases": ["店员", "林同学"],
    "world_ids": ["rainy-bookshop"],
    "bio": "温和细致的旧书屋店员。",
    "sprites": {
      "neutral": "/media/browser/assets/rainy-bookshop/lin-deng/neutral.png",
      "thinking": "/media/browser/assets/rainy-bookshop/lin-deng/thinking.png"
    },
    "avatar": "/media/browser/assets/rainy-bookshop/lin-deng/avatar.png",
    "reference": "/media/browser/assets/rainy-bookshop/lin-deng/neutral.png",
    "default_appearance": "bookshop-apron",
    "backgrounds": {
      "bookshop-rain": "/media/browser/assets/rainy-bookshop/bookshop-rain.png"
    },
    "background_descriptions": {"bookshop-rain": "雨后傍晚的旧书屋"}
  }
}
```

这是接图的格式示范，路径对应的 PNG 必须先真正存在；不要直接写不存在的文件。锚点人物的视觉配置提供剧本选择页立绘和背景列表；其他人物各用自己的配置。人物图鉴头像还可直接写在设定卡 `avatar` 中。

优先同一作品、同一美术版本的透明立绘，缺项再用参考图补画。保持人物身份、服装、姿势、比例和上色一致；立绘透明、完整保留头部，背景不含 UI。来源、版权状态和补画提示词应随素材保存。人物有立绘时隐藏对白头像，没有立绘才用同一人物头像。

准备好的初始背景要用与开场相同的键登记。后续新环境可以边玩边生成：生成完成再切换，期间保留现有画面并显示场景过渡。预测素材单独存放，按每棵存档树的配额预制背景 2、立绘 3、交流图 1；真实使用才进入画廊并释放名额。预测内容不写入剧情记忆，不强制发生未来事件。

## 5. 导入和验证

在 Yukino 0.8 公共项目根目录中，先启动一次演示以初始化本地库，再，使用项目内技能和独立库：

```powershell
$storySkill = Join-Path (Get-Location) 'skills/sillytavern-roleplay'
$storyRoot = Join-Path (Get-Location) 'database/roleplay-library'
$storyPackage = Join-Path (Get-Location) 'examples/rainy-bookshop.json'
python -X utf8 "$storySkill/scripts/worlds.py" --root "$storyRoot" import-script "$storyPackage"
python -X utf8 "$storySkill/scripts/worlds.py" --root "$storyRoot" list
python -X utf8 launch.py --check
python -X utf8 launch.py --open
```

以上导入会先验证完整包，再写入所指定的库。查看目录不请求模型。启动器会检查并复用同一资料库的已有舞台，不自动改写当前存档。

导入成功输出 `script_id`、`name`、`opening_count`、`setting_set_ids` 和 `primary_card_id`。网页刷新后，应出现“雨后书屋”，图鉴可查看林灯和阿澈，新建存档可选“雨停之前”与“归还的旧书”。已有舞台一般无需重启；刷新目录即可。

如果希望先独立试验，可将上面的 `--root` 改成你自己指定的临时目录，例如 `$env:TEMP` 下一个新建目录；示例自带人物卡，能在空库完整导入。试验后只向正式项目库导入确认好的包。

启用自动对白前，在本机配置 DeepSeek 密钥；发布副本不包含 API 密钥：

```powershell
python -X utf8 "$storySkill/scripts/deepseek_client.py" --root "$storyRoot" --configure-key
```

也可使用本机 `DEEPSEEK_API_KEY` 环境变量。密钥只在服务端读取，不写人物卡。动态生图沿用本机登录的 Codex CLI；纯文本角色扮演和浏览器舞台的连接方式见技能 `references/browser.md`。

## 6. 更新、旧存档与常见问题

已有存档冻结了开始时的世界观、设定集、人设和主角资料。更新同 ID 剧本的目录资料只影响新建故事；继续旧档仍用其快照。不要为了更新素材把别人的关系或未来剧情写进旧档。

明确要让某个旧档采用新世界观时，先等当前回合完成，再由 Codex 针对指定 `session_id` 使用 `worlds.py attach` 并恢复该档。它改变该档世界快照，不等同于回溯；回溯应在“脉络”中创建新的分支，保留父档和原有记忆。

| 现象 | 核对方法 |
| --- | --- |
| 新剧本不显示 | 检查导入的 root 是否为目标资料库、世界是否有 `opening_scenes`、锚点是否存在，然后刷新网页 |
| “角色卡 ID 已存在不同内容” | 给修改后的人物新的 `card_id`，同步改世界锚点和设定卡引用 |
| 设定集不存在 | `setting_set_ids` 要引用本包或已导入的集，先检查拼写 |
| 人物只有姓名 | 检查该人物独立素材是否存在及 `card_id` 是否一致；没有素材时姓名占位是正常行为 |
| 开场背景不对应 | 开场 `background` 键须对应锚点视觉配置 `backgrounds`；JSON 导入不会自动生成缺图 |
| 简介出现模型指令 | 单独整理 `biography`、`short_personality`、展示 personality，不把 AI 约束贴进图鉴 |
| 新背景没立即出现 | 新图异步生成；确认本机 Codex 能生图，在生成完成前保留现有画面 |
| 更新剧本后旧档没有变化 | 这是独立存档快照的正常行为；新建故事可采用新资料 |
| `verify.py` 提示文件变化 | 它只校验公开种子与代码；私人运行库不参与哈希校验，修改程序或 examples 后应更新发布清单 |

技能自带的 `assets/world-templates/oregairu-script.json` 是更大的春物范例，包含 14 位人物、校园设定和三个原创开场。公共壳已经预装该剧本并默认选择它，可直接游玩或学习其结构；自创剧本不要复制其人物关系或把未来情节写成已发生事实。


## 初始关系与共用素材字段

人物的 `age` 用于图鉴；`initial_affinity` 按主角 ID 和 default 分别保存 score、relationship、basis、version，只将数值和状况展示给玩家。字段格式与春物预设说明见 [好感设定](affinity.md)。世界观可配置 `visual_revision` 和 `visual_locations`；背景身份、图库引用与三类预算见 [图库与配额](shared-gallery.md)。普通导入不改旧档；明确授权的数据迁移须备份并分别修正每个节点。
