# 预制故事线（引擎5.3）

读取、创建或导入传统视觉小说式故事线时使用。剧本仍由世界观、设定集与可选玩法组成；预制线是世界观携带的可选数据，不在主程序写某部作品的专用剧情。

自由故事继续由文本模型生成；预制主线由作者写好的节点直接播放，不调用文本模型、不自动续写。可在next节点上设置free_window开放正常对话与行动；输入调用既有文本管道，返回主线才推进作者节点。制作教程与完整例子见[storyline-authoring.md](storyline-authoring.md)。玩家逐段推进并选择，所有人物对白按自己的署名进入回看。结局停留在最后一幕，可从脉络回溯并另建分支。新建页面在自由开场之后列出预制线，加载存档沿用原模式，不能把已有自由存档无声改成预制线。

## 导入与目录

完整示例在 `assets/storylines/oregairu-volume14-short.json`；它也嵌入 `assets/world-templates/oregairu-script.json`。这是最终卷时期的原创短篇互动改编，含剧透、原创对白和明确标记的IF结局，不声称逐章还原小说。其初始关系仅用于这条新故事，不覆盖第一季自由剧本或旧存档。

目录包可使用：

```text
my-script/
  manifest.json
  world.json
  settings.json
  storylines/short.json
  world-gameplay/...
```

manifest 与原格式相同：world和setting_sets引用文件，可选world_gameplay引用规则代码。world.json 增加 `"storylines": ["storylines/short.json"]`，路径相对manifest目录且不得越界；单JSON包则直接内嵌故事线对象。通过 `worlds.py --root <库> validate-script <包目录或JSON>` 检查，再 `import-script`。不要用导入替换用户正在玩的剧本快照。

## 节点协议

```json
{
  "spec":"yukima_storyline_v1", "id":"short-route", "version":"1.0.0",
  "title":"一场短篇", "description":"面向玩家的简介与剧透提示",
  "start":"arrival", "protagonist_id":"hachiman",
  "nodes":{
    "arrival":{
      "title":"门前", "scene":"总武高中走廊", "background":"corridor",
      "present":[],
      "frames":[{"kind":"narration","speaker":"","text":"走廊安静下来。","expression":"absent"}],
      "choices":[{"id":"leave","text":"【动作】离开学校。","target":"end","set":{"left":true}}]
    },
    "end":{
      "title":"归途", "scene":"总武高中走廊", "background":"corridor",
      "present":[], "frames":[{"kind":"narration","speaker":"","text":"你收好书包。","expression":"absent"}],
      "ending":"归途"
    }
  }
}
```

每节点1–12帧；kind为dialogue/narration，speaker填写设定集的准确姓名，主角使用player。present仅列本幕真实在场NPC；可用audience限定同处本幕的实际听众，缺省为在场人物与主角。旁白不假称为角色对白，不用NPC心声推动作者没有交代的秘密。场景内有离场/到场变化时拆成节点，以保持空间与知情范围明确。

节点必须有next、1–3个choices或ending之一。choice包含唯一id、带输入前缀的text、target；可选set写入本分支标记，when以键值相等限制可用选项。条件不能制造死路，编写后实际遍历允许的选择，不只检查静态连线。不可达、失去结局路径、离场人物对白、未知人物、缺失目标在导入时拒绝。

effects调用通用time/items/relations/threads能力，必须有实际事件reason。时间一次最多7天，更长时间拆成多项。亲密关系变化必须在同节点包含双方明确表达，不能靠分数强制。initial_affinity与initial_relations仅设定新线开场的既有经历，分数是游戏解释而非原作官方数字。

可选backgrounds将背景键映射到本地资源对象，例如 {"spring-room":{"url":"/storyline-backgrounds/clubroom-spring-rain.png","name":"春雨中的侍奉部"}}，仅对本线有效。资源需随舞台assets部署，不能引用外部网站或越界路径；旧档的资源URL须保持可用。background使用本线或人物已登记的场景键，发布前检查素材真实存在、地点季节匹配。不要期待每一幕即时生图才可阅读。当前播放器不会为预制线主动生成预测图；自由故事的图像预测保持原逻辑。

## 存档与接口

POST /api/start 增加可选storyline_id。POST /api/storyline/advance 接受session_id、request_id、node_id和可选choice_id；选择/后续帧/世界效果/人物观察/脉络在同一次commit里保存。重复请求不重复结算；过时节点、模式或请求冲突拒绝。

POST /api/storyline/cursor 保存frame_cursor，限定当前session、node与turn_id；新版界面携带当前轮编号，拒绝旧回复的延迟阅读请求。读取恢复该幕阅读位置，隐藏心声不计入分镜。原有手动另存、管理、回看导出、节点回溯共用，不新增第二套存档格式。browser_authored保存线编号、版本、内容哈希、当前节点、标记和已选记录；完整故事冻结在world_snapshot。API只公开当前可用选项，不公开未来分镜或未选分支内容。

回溯仅继承真实节点快照及以前的记忆/世界状态，原路线保留。更新故事内容只影响新档，旧档仍采用冻结内容。未来升级必须显式创建兼容分支，不能按新内容猜测旧档进度。

自由活动字段：description（玩家说明）、context（当前模型背景）、max_turns（兼容旧字段，不再限制互动次数）、return_text（带【动作】前缀的接续行动）。目标主线必须以旁白开头。browser_authored.free_turns与free_minutes随正常commit保存，互动统计不形成配额；接续时归档当前目标证据与边界历史。AI不接收未来节点，只获得当前自由段与已发生的经历。主线phase、作者定义的主线事件和关系身份由宿主保护；自由叙事仍需试玩核对，具体见制作教程。

5.3目标阶段：free_window.goal含title、criteria、boundaries、converge、conclude_text。next为预设方法路径；自由达标后POST advance choice_id=goal-complete走converge，宿主检查全部证据。证据仅接受本轮非内心输入与非心声分镜中的真实摘录；未知id不写入。语义完成判定依赖模型，需试玩。无互动配额，旧max_turns不执行；目标进展、来源与边界历史随正常存档、回溯隔离。


### 5.6 播放与条件检查

读完当前节点最后一段可见分镜后才可推进。角色心声不占阅读推进位置；刷新恢复已保存位置。目标自由段达标后直接进入 `goal.converge`，不重播预设方法的对话。导入检查可达的“节点+标记”状态，拒绝所有选项隐藏或条件状态无法到达结局的路线；状态组合超过10,000需要简化。预制背景在实际访问后加入分支画廊与公共图库，可按 [调整画面](image-adjustments.md) 另存新版。旧档继续冻结路线，不自动升级故事内容。
