# 角色卡兼容范围

本适配保留原卡 JSON 的未知字段，按文字扮演需要读取常用字段。它是 Codex 的对话技能，不实现整个 SillyTavern 前端或所有扩展运行时。

## 导入

- V1 顶层字段包装为 V2；V2/V3 保留对应 envelope 与额外字段。
- PNG/APNG 读取 chara 或 ccv3 的 base64 UTF-8 JSON，优先 ccv3。兼容 tEXt、zTXt 和 iTXt，检查文本块 checksum 与数据边界。
- 支持 UTF-8 BOM JSON；JSON/元数据上限 16 MiB，整个卡片文件上限 64 MiB。
- WEBP、JPEG、CHARX 暂不解包。用户可从原平台导出 PNG 或 JSON。不要把 WEBP 当 PNG，也不要宣称已加载其元数据。
- 普通图片没有角色元数据时拒绝；程序不会据图编造人设。
- 独立世界书支持 entries 数组或 keyed object，导入时把条目合并到角色内。

## 世界书

使用最近消息中的文字进行字面关键词匹配。尊重 enabled/disable、constant、keys/key、secondary_keys/keysecondary、selective、大小写、整词、scan_depth/scanDepth 与 insertion_order/order；constant 优先装入，之后按高 order 优先分配上下文预算，最后按低到高 order 展示。

主关键词是任一命中；有次要关键词且 selective 开启时，默认 AND ANY，extensions.selectiveLogic 的 0/1/2/3 分别为 AND ANY/NOT ALL/NOT ANY/AND ALL。没有次要关键词时不加过滤条件。中文默认使用子串匹配，不强制英文式词边界。

世界书实际装载以字符数预算控制（默认 12,000），不是精确 tokenizer；没有实现卡片 token_budget。超预算条目会带警告并整体跳过，不截断事实。

不执行 regex 关键词、递归触发、概率、分组互斥、sticky/cooldown/delay、向量检索、精确 depth/role 插入等 ST 扩展语义。卡片依赖这些规则时不要声称完全兼容；说明具体差异，并按用户意图改成简单文字规则或另做扩展。不能把未触发的全部世界书一股脑当已知剧情。

## 宏和脚本

脚本一次性替换 {{char}}/{{user}}；玩家称呼即使带有宏样式文本也不会再次执行。{{original}} 替换为空字符串，因为没有对应酒馆预设。

未支持的宏保留原文，Codex 不能直接把这些字符串发给玩家。对简单随机选项，可在生成对白时选择并在回合中记录；若骰子结果影响数值或分支，使用 Python secrets/system RNG 真实抽取并记录结果，不能声称模型猜的数字是实际掷骰。复杂宏/变量控制需告知兼容差异。

卡片内的 JS、正则替换、MVU/Zod 变量更新、HTML UI、TTS、Live2D、外链资源都不执行或自动安装。需要某个效果时先查看具体依赖与用户意图。没有实现数值引擎的卡片只能以已确认叙事状态保存，不能冒充已验证的战斗/经济模拟。

## 格式依据

- [Character Card V2 specification](https://github.com/malfoyslastname/character-card-spec-v2/blob/main/spec_v2.md)
- [Character Card V3 specification](https://github.com/kwaroran/character-card-spec-v3/blob/main/SPEC_V3.md)
- [SillyTavern World Info](https://docs.sillytavern.app/usage/core-concepts/worldinfo/)

这些链接是实现依据，只有解释或扩展格式时才需要联网读取；日常本地扮演无需网络。
