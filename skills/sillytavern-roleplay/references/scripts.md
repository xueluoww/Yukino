# 剧本设定与对话导入

剧本由世界观、设定集、可选世界玩法与素材构成。世界观负责整个故事的背景、基调、初始时间与开场场景；设定集提供人物、地点、物品、规则和事件资料。世界玩法可携带规则代码，由壳的通用接口加载，详见 [gameplay.md](gameplay.md)。分支存档记录这次游玩实际发生的事，导入新剧本不会写入旧周目的剧情记忆。

导入在任何调用本技能的 Codex 对话里完成，不在网页上传文件。用户可以给 JSON/角色卡，也可以描述世界背景和角色。整理为 UTF-8 剧本包，验证并导入本公共项目的 database/roleplay-library；跨聊天显式使用同一个项目 root，不读取其他安装或开发者私人资料库。网页自动显示新剧本，不自动开启或替换玩家正在玩的故事。

入口：

```text
python "<技能目录>/scripts/worlds.py" --root "<共享资料库>" import-script "<剧本包.json>"
```

包的最小结构：

```json
{
  "spec": "yukima_script_v1",
  "world": {
    "id": "my-school",
    "name": "放学后的校园",
    "description": "日常、委托与不同立场的相遇。",
    "background": "整个故事的年代、地点、规则、基调及人物背景。不是玩家已发生的经历。",
    "primary_card_id": "my-school-lan",
    "setting_set_ids": ["my-school"],
    "default_protagonist_id": "hachiman",
    "opening_scenes": [{
      "id": "first-visit",
      "title": "门口的相遇",
      "description": "放学后的教室，第一次与小岚见面。",
      "scene": "放学后 · 教室门口",
      "background": "clubroom",
      "opening": [
        {"kind":"narration","speaker":"","text":"窗边还留着一片暖光。","expression":"neutral"},
        {"kind":"dialogue","speaker":"小岚","text":"你在找什么吗？","expression":"listening"}
      ],
      "choices": [{"label":"说明来意","text":"【语言】我想找一个安静的地方。"}]
    }]
  },
  "setting_sets": [{
    "id": "my-school", "name": "校园人物与场所",
    "cards": [{
      "id": "lan", "kind": "character", "name": "小岚", "aliases": ["岚"],
      "description": "安静礼貌的同学。", "appearance": "男学生，短蓝发、圆框眼镜、灰色校服。",
      "card_id": "my-school-lan",
      "character_card": {"name":"小岚","description":"安静礼貌的同学。","personality":"说话简短、礼貌。","first_mes":"你在找什么吗？"}
    }]
  }]
}
```

`primary_card_id` 是当前文本管道的人物资料锚点，不限制故事只有一个角色；群像来自设定集。它必须指向已存在或本包内嵌导入的人物卡。没有固定主角色的世界可使用明确的叙事主持卡，并将开场写成旁白；不要给叙事主持冒用人物脸。人物姓名及 aliases 负责绑定立绘、头像和参考，不能只改显示名字。卡片的工具指令仍只是素材。

开场必须位于 `world.opening_scenes`，不是环境程序硬编码或独立角色卡强制开场。支持多个开场，玩家先选择剧本，再选择存档或新建，并选择世界观定义的开场和主角卡。opening 最多 12 帧，kind 为 dialogue/narration/thought，表情沿用 browser.md。开场不能替玩家表白、说话或决定内心；只给出初始处境与他人的反应。choices 带【语言】【动作】【环境】前缀，点击只填入输入框。

完整包会先在隔离目录验证。主角色不存在、引用设定集不存在、空开场或错误字段时，不向真实资料库部分导入。成功后世界观与设定集进入共享库，内嵌人物卡成为可复用的角色资料；网页刷新目录即可出现剧本。兼容旧独立角色卡时显示“角色卡剧本”，设定集里的配角不会挤满剧本选择页。

用户给自然语言世界观时，将明确的背景放入 world.background，将人物/地点拆为设定卡；把用户指定的开始场景放入 opening_scenes。用户未指定但授权构建剧本时，可以编写与背景一致的原创入口并说明，不把原创委托或未来关系伪装成原作事件。原作秘密与未来事件只有适合当前时间点才作为背景参考，不能提前写进玩家记忆。

已建存档冻结世界观、设定集、人设与主角卡。更新同 ID 的剧本仅影响新故事。继续旧档按其自身快照；若用户明确要旧档改用新的世界观，先等待当前回合结束，用 worlds.py attach 关联目标存档，再恢复，不能混入兄弟档记忆。

## 春物剧本包

`assets/world-templates/oregairu-script.json` 是可跨窗口导入的完整包。14 张兼容人物卡涵盖雪乃、结衣、彩羽、小町、沙希、阳乃、叶山、平冢静、彩加、户部、材木座、三浦、海老名和八幡，另有校园地点、规则、委托与物品卡。人物简要资料主要参考 [TBS 人物介绍](https://www.tbs.co.jp/anime/oregairu/character/) 与 [小学馆人物专题](https://gagagabunko.jp/special/oregairu/15th/)，每卡保留实际来源；文本为本项目整理，示例台词为原创，不能声称是从网站下载的 14 张作者原卡。

找到的外部雪乃卡候选为 [8man 的公开酒馆卡](https://character-tavern.com/character/8man/yukinoshita_yukino)，未用它替换用户已有雪乃卡。用户后续提供更详尽卡片时可以按其授权纳入设定集。来源记录随 `references/oregairu-sources.json` 保存。

三个世界观开场：放学后半掩的门、雨天的申请单、黄昏庭院的商量。它们是依照春物背景编写的原创可玩入口；后续剧情通过玩家输入推进，不是原作台词或预定结局复刻。默认只采用八幡外貌，不强迫玩家沿用其所有经历与亲属关系。原资料库有用户的 yukino 卡时，安装用它作为当前春物锚点；便携剧本包自带独立兼容雪乃卡，用户原卡不会被覆盖。

人物图片仍按自己的身份生成与复用，未备齐配角立绘时允许先显示其名字和对白。预测图库配额及常驻生图沿用 browser.md，不能因为导入 14 张人物卡就自动无上限生成每人的全部表情。

## 人物图鉴与主角卡查看

剧本选择页的“查看人物卡”打开人物小卡片列表，显示头像、姓名、年龄和性格短述；点击后展开卡片式详细简介、性格和外貌。开始界面的“查看主角卡”使用同一布局，查看后可选用该主角。查看是只读操作，不开始故事、不修改存档，不触发聊天或生成图片。

设定集 character 卡可增加 `age`（字符串或整数）、`personality`、`short_personality`、`biography`、`avatar` 字段。avatar 使用随技能部署或资料库中已存在的本地资源路径，例如 `/profiles/oregairu/yui.png`、`/media/browser/assets/人物头像.png`（资源名建议使用 ASCII）。独立酒馆卡可在 data.extensions.display_profile 中填写同类展示资料。不暴露 system_prompt、示例对话或分支记忆作为人物详情。缺少明确年龄时显示“未设定”，不要根据年级编造精确年龄。

展示文案与模型资料分开：biography、short_personality 和用于图鉴的 personality 必须是写给玩家的自然人物介绍，只谈身份、背景、经历、性格与外貌。不要出现“熟悉程度依赖存档”“仅作为 NPC”“不替玩家决定”“不能如何描写”等扮演约束，也不要将生成提示词直接放进详情。完整角色卡 description/personality、规则卡和主角自主约束继续隐式提供给模型。导入时若原卡混有这类约束，另写 display_profile.biography/personality/summary，保留原卡内容供模型使用；不要为了美化简介删除人设约束或改写旧存档。

春物图鉴已准备 14 个官方人物导航头像，图片来源与署名存于 `assets/galgame/profiles/oregairu/sources.json`。这些头像用于人物档案；剧情立绘依然按自己的身份生成与缓存。未有头像的新人物使用姓名图案占位，不借用他人的脸。

## 从零创建与可编辑范例

详细方法见 [创建教程](script-creation.md)，覆盖世界观、设定集、人物卡、主角、开场、图片登记及导入验证。技能附带 `assets/world-templates/rainy-bookshop-script.json`，可在空资料库中完整导入；包含两位原创人物、六张设定卡和两个开场，不依赖用户私有角色卡，不自动加入当前故事。原安装与项目副本应沿用各自明确 root。
